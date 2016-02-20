#!/usr/bin/env python3
from argparse import ArgumentParser
from aiohttp import web
from ipdb import set_trace as bp
import aiohttp, asyncio, inspect, json, logging, os, pprint, random, re, \
    signal, ssl, string, sys, time, traceback, uuid, weakref

logger = logging.getLogger('wechatircd')

def debug(msg, *args):
    logger.debug(msg, *args)

def info(msg, *args):
    logger.info(msg, *args)

def warning(msg, *args):
    logger.warning(msg, *args)

def error(msg, *args):
    logger.error(msg, *args)

class ExceptionHook(object):
    instance = None
    def __call__(self, *args, **kwargs):
        if self.instance is None:
            from IPython.core import ultratb
            self.instance = ultratb.VerboseTB(call_pdb=True)
        return self.instance(*args, **kwargs)

### HTTP serving webwxapp.js & WebSocket server

class Web:
    instance = None

    def __init__(self):
        with open(os.path.join(os.path.dirname(__file__), 'webwxapp.js'), 'rb') as f:
            self.webwxapp_js = f.read()
        self.token2ws = {}
        self.ws2token = {}
        assert not Web.instance
        Web.instance = self

    def remove_ws(self, ws, peername):
        token = self.ws2token.pop(ws)
        del self.token2ws[token]
        Server.instance.on_wechat_close(token, peername)

    def remove_token(self, token, peername):
        del self.ws2token[self.token2ws[token]]
        del self.token2ws[token]
        Server.instance.on_wechat_close(token, peername)

    async def handle_webwxapp_js(self, request):
        return web.Response(body=self.webwxapp_js,
                            headers={'Content-Type': 'application/javascript; charset=UTF-8',
                                     'Access-Control-Allow-Origin': '*'})

    async def handle_web_socket(self, request):
        ws = web.WebSocketResponse()
        peername = request.transport.get_extra_info('peername')
        info('WebSocket connected to %r', peername)
        await ws.prepare(request)
        async for msg in ws:
            if msg.tp == web.MsgType.text:
                try:
                    data = json.loads(msg.data)
                    token = data['token']
                    assert isinstance(token, str) and re.match(r'^[0-9a-f]{32}$', token)
                    if ws in self.ws2token:
                        if self.ws2token[ws] != token:
                            self.remove_ws(ws, peername)
                    if ws not in self.ws2token:
                        if token in self.token2ws:
                            self.remove_token(token, peername)
                        self.ws2token[ws] = token
                        self.token2ws[token] = ws
                        Server.instance.on_wechat_open(token, peername)
                    Server.instance.on_wechat(data)
                except AssertionError:
                    break
                except:
                    raise
            elif msg.tp == web.MsgType.ping:
                try:
                    ws.pong()
                except:
                    break
            elif msg.tp == web.MsgType.close:
                break
        info('WebSocket disconnected from %r', peername)
        if ws in self.ws2token:
            self.remove_ws(ws, peername)
        return ws

    def start(self, host, port, tls, loop):
        self.loop = loop
        self.app = aiohttp.web.Application()
        self.app.router.add_route('GET', '/', self.handle_web_socket)
        self.app.router.add_route('GET', '/webwxapp.js', self.handle_webwxapp_js)
        self.handler = self.app.make_handler()
        self.srv = loop.run_until_complete(loop.create_server(self.handler, host, port, ssl=tls))

    def stop(self):
        self.srv.close()
        self.loop.run_until_complete(self.srv.wait_closed())
        self.loop.run_until_complete(self.app.shutdown())
        self.loop.run_until_complete(self.handler.finish_connections(0))
        self.loop.run_until_complete(self.app.cleanup())

    def send_text_message(self, token, receiver, msg):
        if token in self.token2ws:
            ws = self.token2ws[token]
            try:
                ws.send_str(json.dumps({
                    'command': 'send_text_message',
                    'receiver': receiver,
                    'message': msg,
                    #@ webwxapp.js /e.ClientMsgId = e.LocalID = e.MsgId = (utilFactory.now() + Math.random().toFixed(3)).replace(".", ""),
                    'local_id': '{}0{:03}'.format(int(time.time()*1000), random.randint(0, 999)),
                }))
            except:
                pass

    def add_member(self, token, roomname, username):
        if token in self.token2ws:
            ws = self.token2ws[token]
            try:
                ws.send_str(json.dumps({
                    'command': 'add_member',
                    'room': roomname,
                    'user': username,
                }))
            except:
                pass

    def del_member(self, token, roomname, username):
        if token in self.token2ws:
            ws = self.token2ws[token]
            try:
                ws.send_str(json.dumps({
                    'command': 'del_member',
                    'room': roomname,
                    'user': username,
                }))
            except:
                pass

    def mod_topic(self, token, roomname, topic):
        if token in self.token2ws:
            ws = self.token2ws[token]
            try:
                ws.send_str(json.dumps({
                    'command': 'mod_topic',
                    'room': roomname,
                    'topic': topic,
                }))
            except:
                pass

### IRC utilities

def irc_lower(s):
    irc_trans = str.maketrans(string.ascii_uppercase+'[]\\^',
                              string.ascii_lowercase+'{}|~')
    return s.translate(irc_trans)


# loose
def irc_escape(s):
    s = re.sub(r',', '.', s)
    s = re.sub(r'<[^>]*>', '', s)
    return re.sub(r'[^-\w$%^*()=./]', '', s)

### Commands

class UnregisteredCommands:
    @staticmethod
    def nick(client, *args):
        if not args:
            client.err_nonicknamegiven()
            return
        client.server.change_nick(client, args[0])

    @staticmethod
    def user(client, user, mode, _, realname):
        client.user = user
        client.realname = realname

    @staticmethod
    def quit(client):
        client.disconnect('Client quit')


class RegisteredCommands:
    @staticmethod
    def away(client):
        pass

    @staticmethod
    def invite(client, nick, channelname):
        if client.is_in_channel(channelname):
            client.get_channel(channelname).on_invite(client, nick)
        else:
            client.err_notonchannel(channelname)

    @staticmethod
    def ison(client, *nicks):
        client.reply('303 {} :{}', client.nick,
                     ' '.join(nick for nick in nicks \
                              if client.has_wechat_user(nick) or
                              client.server.has_nick(nick)))

    @staticmethod
    def join(client, arg):
        if arg == '0':
            for channel in client.channels.values():
                channel.on_part(client, channel.name)
        else:
            for channelname in arg.split(','):
                if not client.is_in_channel(channelname):
                    try:
                        channel = client.server.ensure_channel(channelname)
                        channel.on_join(client)
                    except ValueError:
                        client.err_nosuchchannel(channelname)

    @staticmethod
    def kick(client, channelname, nick, reason=None):
        if client.is_in_channel(channelname):
            client.get_channel(channelname).on_kick(client, nick, reason)
        else:
            client.err_notonchannel(channelname)

    @staticmethod
    def lusers(client):
        client.reply('251 :There are {} users', len(client.server.nicks))

    @staticmethod
    def mode(client, target, *args):
        if client.has_wechat_user(target):
            if args:
                client.err_umodeunknownflag()
            else:
                client.rpl_umodeis('')
        elif client.server.has_nick(target):
            if args:
                client.err_umodeunknownflag()
            else:
                client2 = client.server.get_nick(target)
                client.rpl_umodeis(client2.mode)
        elif client.is_in_channel(target):
            client.get_channel(target).on_mode(client)
        elif client.server.has_channel(target):
            client.server.get_channel(target).on_mode(client)
        else:
            client.err_nosuchchannel(target)

    @staticmethod
    def names(client, target):
        if not client.is_in_channel(target):
            client.err_notonchannel(target)
            return
        client.get_channel(target).on_names(client)

    @staticmethod
    def nick(client, *args):
        if not args:
            client.err_nonicknamegiven()
            return
        client.server.change_nick(client, args[0])

    @staticmethod
    def notice(client, *args):
        RegisteredCommands.notice_or_privmsg(client, 'NOTICE', *args)

    @staticmethod
    def part(client, arg, *args):
        partmsg = args[0] if args else None
        for channelname in arg.split(','):
            if client.is_in_channel(channelname):
                client.get_channel(channelname).on_part(client, partmsg)
            else:
                client.err_notonchannel(channelname)

    @staticmethod
    def ping(client, *args):
        if not args:
            client.err_noorigin()
            return
        client.reply('PONG {} :{}', client.server.name, args[0])

    @staticmethod
    def pong(client, *args):
        pass

    @staticmethod
    def privmsg(client, *args):
        RegisteredCommands.notice_or_privmsg(client, 'PRIVMSG', *args)

    @staticmethod
    def quit(client, *args):
        client.disconnect(args[0] if args else client.prefix)

    @staticmethod
    def topic(client, channelname, new=None):
        if not client.is_in_channel(channelname):
            client.err_notonchannel(channelname)
            return
        client.get_channel(channelname).on_topic(client, new)

    @staticmethod
    def who(client, target):
        if client.has_wechat_user(target):
            pass
        elif client.server.has_nick(target):
            pass
        elif client.is_in_channel(target):
            client.get_channel(target).on_who(client)
        elif client.server.has_channel(target):
            client.server.get_channel(client, target).on_who(client)
        client.reply('315 {} {} :End of WHO list', client.nick, target)

    @classmethod
    def notice_or_privmsg(cls, client, command, *args):
        if not args:
            client.err_norecipient(command)
            return
        if len(args) == 1:
            client.err_notexttosend()
            return
        target = args[0]
        msg = args[1]
        # on name conflict, prefer to resolve WeChat user first
        if client.has_wechat_user(target):
            user = client.get_wechat_user(target)
            if user.is_friend:
                Web.instance.send_text_message(client.token, user.username, msg)
            else:
                client.err_nosuchnick(target)
        # then IRC nick
        elif client.server.has_nick(target):
            client2 = client.server.get_nick(target)
            client2.write(':{} {} {} :{}'.format(client.prefix, 'PRIVMSG', target, msg))
        # IRC channel or WeChat chatroom
        elif client.is_in_channel(target):
            channel = client.get_channel(target).on_notice_or_privmsg(client, command, msg)
        else:
            client.err_nosuchnick(target)


class WeChatCommands:
    @staticmethod
    def user(client, data):
        debug({k: v for k, v in data['record'].items() if k in ['UserName','DisplayName','NickName']})
        client.ensure_wechat_user(data['record'])

    @staticmethod
    def room(client, data):
        debug({k: v for k, v in data['record'].items() if k in ['UserName','DisplayName','NickName']})
        record = data['record']
        room = client.ensure_wechat_room(record)
        if isinstance(record.get('MemberList'), list):
            room.update_members(client, record['MemberList'])

    @staticmethod
    def message(client, data):
        msg = data['message']
        # WeChat chatroom
        if data.get('room', None):
            room = client.ensure_wechat_room(data['room'])
            if data['type'] == 'send':
                # server generated messages have been filtered by client-side JS
                client.write(':{} PRIVMSG {} :{}'.format(
                    client.prefix, room.name, msg))
            else:
                # For chatroom events, sender is the same as receiver, e.g. 你邀请xxx加入了群聊
                if data['sender'] == room.username:
                    client.write(':{} PRIVMSG {} :{}'.format(
                        peer.nick, room.name, msg))
                else:
                    peer = client.ensure_wechat_user(data['sender'])
                    client.write(':{} PRIVMSG {} :{}'.format(
                        peer.nick, room.name, msg))
        # 微信朋友
        else:
            peer = client.ensure_wechat_user(data['receiver' if data['type'] == 'send' else 'sender'])
            if data['type'] == 'send':
                client.write(':{} PRIVMSG {} :{}'.format(
                    client.prefix, peer.nick, msg))
            else:
                client.write(':{} PRIVMSG {} :{}'.format(
                    peer.nick, client.nick, msg))

    @staticmethod
    def send_text_message_fail(client, data):
        client.write(':{} NOTICE {} :{}'.format(client.server.name, '+status', 'failed: {}'.format(data['message'])))

### Channels: StandardChannel > StatusChannel, WeChatRoom

class Channel:
    def __init__(self, name):
        self.name = name
        self.topic = ''
        self.mode = ''

    @property
    def prefix(self):
        return self.name

    def log(self, source, fmt, *args):
        info('%s %s '+fmt, self.name, source.nick, *args)

    def multicast_group(self, source):
        raise NotImplemented

    def event(self, source, command, fmt, *args, include_source=True):
        line = fmt.format(*args) if args else fmt
        for client in self.multicast_group(source):
            if client != source or include_source:
                client.write(':{} {} {}'.format(source.prefix, command, line))

    def deop_event(self, channel, user):
        self.event(channel, 'MODE', '{} -o {}', channel.name, user.nick)

    def nick_event(self, user, new):
        self.event(user, 'NICK', new)

    def join_event(self, user):
        self.event(user, 'JOIN', self.name)
        self.log(user, 'joined')

    def kick_event(self, kicker, channel, kicked, reason=None):
        if reason:
            self.event(kicker, 'KICK', '{} {}: {}', channel.name, kicked.nick, reason)
        else:
            self.event(kicker, 'KICK', '{} {}', channel.name, kicked.nick)
        self.log(kicker, 'kicked %s', kicked.prefix)

    def op_event(self, channel, user):
        self.event(channel, 'MODE', '{} +o {}', channel.name, user.nick)

    def part_event(self, user, partmsg):
        if partmsg:
            self.event(user, 'PART', '{} :{}', self.name, partmsg)
        else:
            self.event(user, 'PART', self.name)
        self.log(user, 'leaved')

    def on_invite(self, client, nick):
        client.err_chanoprivsneeded(self.name)

    # subclasses should return True if succeeded to join
    def on_join(self, client):
        client.enter(self)
        self.join_event(client)
        self.on_topic(client)
        self.on_names(client)

    def on_kick(self, client, nick, reason):
        client.err_chanoprivsneeded(self.name)

    def on_mode(self, client):
        client.rpl_channelmodeis(self.name, self.mode)

    def on_topic(self, client, new=None):
        if new:
            client.err_nochanmodes()
        else:
            if self.topic:
                client.reply('332 {} {} :{}', client.nick, self.name, self.topic)
            else:
                client.reply('331 {} {} :No topic is set', client.nick, self.name)


class StandardChannel(Channel):
    def __init__(self, server, name):
        super().__init__(name)
        self.server = server
        self.members = {}   # Client -> mode

    def multicast_group(self, source):
        return self.members.keys()

    def on_notice_or_privmsg(self, client, command, msg):
        self.event(client, command, '{} :{}', self.name, msg, include_source=False)

    def on_join(self, client):
        if client in self.members:
            return False
        # first user becomes op
        self.members[client] = 'o' if not self.members else ''
        super().on_join(client)
        return True

    def on_kick(self, client, nick, reason):
        if 'o' not in self.members[client]:
            client.err_chanoprivsneeded(self.name)
        elif not client.server.has_nick(nick):
            client.err_usernotinchannel(nick, self.name)
        else:
            user = client.server.get_nick(nick)
            if user not in self.members:
                client.err_usernotinchannel(nick, self.name)
            elif client != user:
                self.kick_event(client, self, user, reason)
                self.on_part(user, None)

    def on_names(self, client):
        client.reply('353 {} = {} :{}', client.nick, self.name,
                     ' '.join(sorted('@'+u.nick if 'o' in m else u.nick
                                     for u, m in self.members.items())))
        client.reply('366 {} {} :End of NAMES list', client.nick, self.name)

    def on_part(self, client, msg):
        if client not in self.members:
            client.err_notonchannel(self.name)
            return False
        if msg: # explicit PART, not disconnection
            self.part_event(client, msg)
        if len(self.members) == 1:
            self.server.remove_channel(self.name)
        elif 'o' in self.members.pop(client):
            user = next(iter(self.members))
            self.members[user] += 'o'
            self.op_event(self, user)
        client.leave(self)
        return True

    def on_topic(self, client, new=None):
        if new:
            self.log(client, 'set topic %r', new)
            self.topic = new
            self.event(client, 'TOPIC', '{} :{}', channel.name, new)
        else:
            super().on_topic(client, new)

    def on_who(self, client):
        for member in self.members:
            member.on_who_member(client, self.name)


# A special channel where each client can only see himself
class StatusChannel(Channel):
    instance = None

    def __init__(self, server):
        super().__init__('+status')
        self.server = server
        self.members = set()
        self.shadow_members = weakref.WeakKeyDictionary()
        assert not StatusChannel.instance
        StatusChannel.instance = self

    def multicast_group(self, source):
        client = source.client if isinstance(source, WeChatUser) else source
        return (client,) if client in self.members else ()

    def respond(self, client, fmt, *args):
        if args:
            client.write((':{} PRIVMSG {} :'+fmt).format(self.name, self.name, *args))
        else:
            client.write((':{} PRIVMSG {} :').format(self.name, self.name)+fmt)

    def on_notice_or_privmsg(self, client, command, msg):
        if client not in self.members:
            client.err_notonchannel(self.name)
            return
        if msg == 'help':
            self.respond(client, 'new [token]  generate new token or use specified token')
            self.respond(client, 'help         display this help')
        elif msg == 'new':
            client.change_token(uuid.uuid1().hex)
            self.respond(client, 'new token {}', client.token)
        elif msg == 'status':
            self.respond(client, 'Token: {}', client.token)
            self.respond(client, 'IRC channels:')
            for name, room in client.channels.items():
                if isinstance(room, StandardChannel):
                    self.respond(client, name)
            self.respond(client, 'WeChat friends:')
            for name, user in client.wechat_users.items():
                if user.is_friend:
                    line = name+':'
                    if user.is_friend:
                        line += ' friend'
                    self.respond(client, line)
            self.respond(client, 'WeChat rooms:')
            for name, room in client.channels.items():
                if isinstance(room, WeChatRoom):
                    self.respond(client, name)
        else:
            m = re.match(r'admin (\S+)$', msg.strip())
            if m and m.group(1) == client.server.options.password:
                self.respond(client, 'Token list:')
                for token, c in client.server.tokens.items():
                    self.respond(client, '{}: {}', token, c.prefix)
            else:
                m = re.match(r'eval (\S+) (.+)$', msg.strip())
                if m and m.group(1) == client.server.options.password:
                    try:
                        r = pprint.pformat(eval(m.group(2)))
                    except:
                        r = traceback.format_exc()
                    for line in r.splitlines():
                        self.respond(client, line)
                else:
                    m = re.match(r'new ([0-9a-f]{32})$', msg.strip())
                    if m:
                        token = m.group(1)
                        if not client.change_token(token):
                            self.respond(client, 'Token {} has been taken', token)
                        elif client.token == token:
                            self.respond(client, 'New token {}', token)
                        else:
                            self.respond(client, 'Token {} has been taken', token)
                    else:
                        self.respond(client, 'Unknown command {}', msg)

    def on_join(self, member):
        if isinstance(member, Client):
            if member in self.members:
                return False
            self.members.add(member)
            super().on_join(member)
        else:
            client = member.client
            if client not in self.shadow_members:
                self.shadow_members[client] = set()
            if member in self.shadow_members[client]:
                return False
            self.shadow_members[client].add(member)
            member.enter(self)
            self.join_event(member)
        return True

    def on_names(self, client):
        members = [x.nick for x in self.shadow_members.get(client, ())]
        members.append(client.nick)
        client.reply('353 {} = {} :{}', client.nick, self.name, ' '.join(sorted(members)))

    def on_part(self, member, msg):
        if isinstance(member, Client):
            if member not in self.members:
                member.err_notonchannel(self.name)
                return False
            if msg: # explicit PART, not disconnection
                self.part_event(member, msg)
            self.members.remove(member)
        else:
            if member not in self.shadow_members[member.client]:
                return False
            self.part_event(member, msg)
            self.shadow_members[member.client].pop(member)
        member.leave(self)
        return True

    def on_who(self, client):
        if client in self.members:
            client.on_who_member(client, self.name)


class WeChatRoom(Channel):
    def __init__(self, client, record):
        super().__init__(None)
        self.client = client
        self.username = record['UserName']
        self.record = {}
        self.joined = False   # JOIN event has not been emitted
        # For large chatrooms, record['MemberList']['Uin'] is very likely
        # to be 0, so the owner is hard to determine.
        # If the owner is determined, he/she is the only op
        self.owner = None
        self.members = set()  # room members excluding `client`, used only for listing
        self.update(client, record)

    def update(self, client, record):
        self.record.update(record)
        self.topic = record['DisplayName']
        old_name = getattr(self, 'name', None)
        base = '&' + irc_escape(record['DisplayName'])
        if base == '&':
            base += '.'.join(member.nick for member in self.members)[:20]
        suffix = ''
        while 1:
            name = base+suffix
            if name == old_name or not client.is_in_channel(base+suffix):
                break
            suffix = str(int(suffix or 0)+1)
        if name != old_name:
            # PART -> rename -> JOIN to notify the IRC client
            self.part_event(client, 'Changing name')
            self.name = name
            self.join_event(client)

    def update_members(self, client, members):
        owner_uin = self.record['OwnerUin']
        owner = None
        seen = set()
        for member in members:
            user = client.ensure_wechat_user(member)
            seen.add(user)
            if owner_uin == user.record['Uin']:
                owner = user
            if user not in self.members:
                self.on_join(user)
        for user in self.members - seen:
            self.on_part(user, self.name)
        self.members = seen
        if self.owner != owner:
            # deop the old owner
            if self.owner:
                self.deop_event(self, self.owner)
            self.owner = owner
            if owner:
                self.op_event(self, owner)

    def multicast_group(self, source):
        if not self.joined:
            return ()
        if isinstance(source, (WeChatUser, WeChatRoom)):
            return (source.client,)
        return (source,)

    def on_notice_or_privmsg(self, client, command, msg):
        Web.instance.send_text_message(client.token, self.username, msg)

    def on_invite(self, client, nick):
        if client.has_wechat_user(nick):
            user = client.get_wechat_user(nick)
            if user in self.members:
                client.err_useronchannel(nick, self.name)
            elif not user.is_friend:
                client.err_nosuchnick(nick)
            else:
                Web.instance.add_member(client.token, self.username, user.username)
        else:
            client.err_nosuchnick(nick)

    def on_join(self, member):
        if isinstance(member, Client):
            if self.joined:
                return False
            self.joined = True
            super().on_join(member)
        else:
            if member in self.members:
                return False
            self.members.add(member)
            member.enter(self)
            self.join_event(member)
        return True

    def on_kick(self, client, nick, reason):
        if client.has_wechat_user(nick):
            user = client.get_wechat_user(nick)
            Web.instance.del_member(client.token, self.username, user.username)
        else:
            client.err_usernotinchannel(nick, self.name)

    def on_names(self, client):
        members = tuple('@'+u.nick if 'o' in m else u.nick
                        for u, m in self.members) + (client.nick,)
        client.reply('353 {} = {} :{}', client.nick, self.name,
                     ' '.join(sorted(members)))
        client.reply('366 {} {} :End of NAMES list', client.nick, self.name)

    def on_part(self, member, msg):
        if isinstance(member, Client):
            if not self.joined:
                member.err_notonchannel(self.name)
                return False
            if msg: # not msg implies being disconnected/kicked/...
                self.part_event(member, msg)
            self.joined = False
        else:
            if member not in self.members:
                return False
            self.part_event(member, msg)
            self.members.remove(member)
        member.leave(self)
        return True

    def on_topic(self, client, new=None):
        if new:
            if True: # TODO is owner
                Web.instance.mod_topic(client.token, self.username, new)
            else:
                client.err_nochanmodes()
        else:
            super().on_topic(client, new)

    def on_who(self, client):
        members = tuple(x.nick for x in self.members)+(client.nick,)
        for member in members:
            member.on_who_member(client, self.name)


class Client:
    def __init__(self, server, reader, writer):
        self.server = server
        self.reader = reader
        self.writer = writer
        peer = writer.get_extra_info('socket').getpeername()
        self.host = peer[0]
        self.user = None
        self.nick = None
        self.registered = False
        self.mode = ''
        self.channels = {}             # name -> IRC channel or WeChat chatroom
        self.username2wechat_room = {} # UserName -> WeChatRoom
        self.wechat_users = {}         # nick -> IRC user or WeChat user (friend or room contact)
        self.username2wechat_user = {} # UserName -> WeChatUser
        self.token = None

    def enter(self, channel):
        self.channels[irc_lower(channel.name)] = channel

    def leave(self, channel):
        del self.channels[irc_lower(channel.name)]

    def change_token(self, new):
        return self.server.change_token(self, new)

    def has_wechat_user(self, nick):
        return irc_lower(nick) in self.wechat_users

    def get_wechat_user(self, nick):
        return self.wechat_users[irc_lower(nick)]

    def remove_wechat_user(self, nick):
        self.wechat_users.pop(irc_lower(nick))

    def ensure_wechat_user(self, record):
        assert isinstance(record['UserName'], str)
        assert isinstance(record['DisplayName'], str)
        if record['UserName'] in self.username2wechat_user:
            user = self.username2wechat_user.pop(record['UserName'])
            self.remove_wechat_user(user.nick)
            user.update(self, record)
        else:
            user = WeChatUser(self, record)
        self.wechat_users[irc_lower(user.nick)] = user
        self.username2wechat_user[user.username] = user
        return user

    def is_in_channel(self, name):
        return irc_lower(name) in self.channels

    def get_channel(self, channelname):
        return self.channels[irc_lower(channelname)]

    def remove_channel(self, channelname):
        del self.channels[irc_lower(channelname)]

    def ensure_wechat_room(self, record):
        assert isinstance(record['UserName'], str)
        assert isinstance(record['DisplayName'], str)
        if record['UserName'] in self.username2wechat_room:
            room = self.username2wechat_room.pop(record['UserName'])
            self.remove_channel(room.name)
            room.update(self, record)
        else:
            room = WeChatRoom(self, record)
            room.on_join(self)
        self.channels[irc_lower(room.name)] = room
        self.username2wechat_room[room.username] = room
        return room

    def disconnect(self, quitmsg):
        self.write('ERROR :{}'.format(quitmsg))
        info('Disconnected from %s', self.prefix)
        self.message_related(False, ':{} QUIT :{}', self.prefix, quitmsg)
        self.writer.write_eof()
        self.writer.close()
        channels = self.channels.values()
        for channel in channels:
            channel.on_part(self, None)

    def reply(self, msg, *args):
        self.write((':{} '+msg).format(self.server.name, *args))

    def write(self, msg):
        try:
            self.writer.write(msg.encode()+b'\n')
        except:
            pass

    @property
    def prefix(self):
        return '{}!{}@{}'.format(self.nick or '', self.user or '', self.host or '')

    def rpl_umodeis(self, mode):
        self.reply('221 {} +{}', self.nick, mode)

    def rpl_channelmodeis(self, channelname, mode):
        self.reply('324 {} {} +{}', self.nick, channelname, mode)

    def err_nosuchnick(self, name):
        self.reply('401 {} :Not such nick/channel', name)

    def err_nosuchchannel(self, channelname):
        self.reply('403 {} :Not such channel', channelname)

    def err_noorigin(self):
        self.reply('409 :Not origin specified')

    def err_norecipient(self, command):
        self.reply('411 :No recipient given ({})', command)

    def err_notexttosend(self):
        self.reply('412 :No text to send')

    def err_unknowncommand(self, command):
        self.reply('421 {} :Unknown command', command)

    def err_nonicknamegiven(self):
        self.reply('431 :No nickname given')

    def err_errorneusnickname(self, nick):
        self.reply('432 {} :Erroneous nickname', nick)

    def err_nicknameinuse(self, nick):
        self.reply('433 {} :Nickname is already in use', nick)

    def err_usernotinchannel(self, nick, channelname):
        self.reply("441 {} {} :They are't on that channel", nick, channelname)

    def err_notonchannel(self, channelname):
        self.reply("442 {} :You're not on that channel", channelname)

    def err_useronchannel(self, nick, channelname):
        self.reply('443 {} {} :is already on channel', nick, channelname)

    def err_needmoreparams(self, command):
        self.reply('461 {} :Not enough parameters', command)

    def err_nochanmodes(self, channelname):
        self.reply("477 {} :You're not on that channel", channelname)

    def err_chanoprivsneeded(self, channelname):
        self.reply("482 {} :You're not channel operator", channelname)

    def err_umodeunknownflag(self):
        self.reply('501 {} :Unknown MODE flag')

    def message_related(self, include_self, fmt, *args):
        '''Send a message to related clients which source is self'''
        clients = set()
        for channel in self.channels.values():
            if isinstance(channel, StandardChannel):
                clients |= channel.members.keys()
        if include_self:
            clients.add(self)
        else:
            clients.discard(self)
        line = fmt.format(*args) if args else fmt
        for client in clients:
            client.write(line)

    def handle_command(self, command, args):
        cls = RegisteredCommands if self.registered else UnregisteredCommands
        ret = False
        cmd = irc_lower(command)
        if type(cls.__dict__.get(cmd)) != staticmethod:
            self.err_unknowncommand(command)
        else:
            fn = getattr(cls, cmd)
            try:
                ba = inspect.signature(fn).bind(self, *args)
            except TypeError:
                self.err_needmoreparams(command)
            else:
                fn(*ba.args)
                if not self.registered and self.user and self.nick:
                    info('%s registered', self.prefix)
                    self.reply('001 {} :Hi, welcome to IRC', self.nick)
                    self.reply('002 {} :Your host is {}', self.nick, self.server.name)
                    RegisteredCommands.lusers(self)
                    self.registered = True

                    status_channel = StatusChannel.instance
                    RegisteredCommands.join(self, status_channel.name)
                    status_channel.on_notice_or_privmsg(self, 'PRIVMSG', 'new')

    async def handle_irc(self):
        sent_ping = False
        while 1:
            try:
                line = await asyncio.wait_for(
                    self.reader.readline(), loop=self.server.loop,
                    timeout=self.server.options.heartbeat)
            except asyncio.TimeoutError:
                if sent_ping:
                    self.disconnect('ping timeout')
                    return
                else:
                    sent_ping = True
                    self.write('PING :'+self.server.name)
                    continue
            if not line:
                return
            line = line.rstrip(b'\r\n').decode('utf-8', 'ignore')
            sent_ping = False
            if not line:
                continue
            x = line.split(' ', 1)
            command = x[0]
            if len(x) == 1:
                args = []
            elif len(x[1]) > 0 and x[1][0] == ':':
                args = [x[1][1:]]
            else:
                y = x[1].split(' :', 1)
                args = y[0].split(' ')
                if len(y) == 2:
                    args.append(y[1])
            self.handle_command(command, args)

    def on_who_member(self, client, channelname):
        client.reply('352 {} {} {} {} {} H :0 {}', client.nick, channelname,
                        self.user, self.host, client.server.name,
                        self.nick, self.realname)

    def on_wechat(self, data):
        command = data['command']
        if type(WeChatCommands.__dict__.get(command)) == staticmethod:
            getattr(WeChatCommands, command)(self, data)

    def on_wechat_open(self, peername):
        status = StatusChannel.instance
        status.event(status, 'NOTICE',
                     '{} :WeChat connected to {}', status.name, peername)

    def on_wechat_close(self, peername):
        for user in self.wechat_users.values():
            StatusChannel.instance.on_part(self, 'WeChat disconnection')
        self.wechat_users.clear()
        self.username2wechat_user.clear()
        # PART all WeChat chatrooms
        for room in self.username2wechat_room.values():
            room.on_part(self, 'WeChat disconnection')
        self.username2wechat_room.clear()
        status = StatusChannel.instance
        status.event(status, 'NOTICE',
                     '{} :WeChat disconnected from ', status.name, peername)


class WeChatUser:
    def __init__(self, client, record):
        self.client = client
        self.username = record['UserName']
        self.channels = set()
        self.is_friend = False
        self.record = {}
        self.update(client, record)

    @property
    def prefix(self):
        return '{}!{}@WeChat'.format(self.nick, self.username.replace('@',''))

    def update(self, client, record):
        self.record.update(record)
        old_nick = getattr(self, 'nick', None)
        # items in MemberList do not have 'DisplayName' or 'RemarkName'
        if self.username.startswith('@'):
            base = re.sub('^[&#!+]*', '', irc_escape(self.record.get('DisplayName', '')))
        # special contacts, e.g. filehelper
        else:
            base = irc_escape(self.username)
        suffix = ''
        while 1:
            nick = base+suffix
            if nick == old_nick or irc_lower(nick) != irc_lower(client.nick) \
                    and not client.has_wechat_user(nick):
                break
            suffix = str(int(suffix or 0)+1)
        if nick != old_nick:
            for channel in self.channels:
                channel.nick_event(self, nick)
            self.nick = nick
        if 'RemarkName' in self.record:
            if not self.is_friend:
                self.is_friend = True
                StatusChannel.instance.on_join(self)

    def enter(self, channel):
        self.channels.add(channel)

    def leave(self, channel):
        self.channels.remove(channel)

    def on_who_member(self, client, channelname):
        client.reply('352 {} {} {} {} {} H :0 {}', client.nick, channelname,
                        self.username, 'WeChat', client.server.name,
                        self.nick, self.username)


class Server:
    valid_nickname = re.compile(r"^[][\`_^{|}A-Za-z][][\`_^{|}A-Za-z0-9-]{0,50}$")
    # initial character `+` is reserved for special channels
    # initial character `&` is reserved for WeChat chatrooms
    valid_channelname = re.compile(r"^[#!][^\x00\x07\x0a\x0d ,:]{0,50}$")
    instance = None

    def __init__(self, options):
        self.options = options
        self.channels = {'+status': StatusChannel(self)}
        self.name = 'meow'
        self.nicks = {}
        self.tokens = {}
        assert not Server.instance
        Server.instance = self

    def _accept(self, reader, writer):
        def done(task):
            if client.nick:
                self.remove_nick(client.nick)
            if client.token:
                del self.tokens[client.token]

        try:
            client = Client(self, reader, writer)
            task = self.loop.create_task(client.handle_irc())
            task.add_done_callback(done)
        except Exception as e:
            traceback.print_exc()

    def has_channel(self, channelname):
        return irc_lower(channelname) in self.channels

    def get_channel(self, channelname):
        return self.channels[irc_lower(channelname)]

    # IRC channel or WeChat chatroom
    def ensure_channel(self, channelname):
        if self.has_channel(channelname):
            return self.channels[irc_lower(channelname)]
        if not Server.valid_channelname.match(channelname):
            raise ValueError
        channel = StandardChannel(self, channelname)
        self.channels[irc_lower(channelname)] = channel
        return channel

    def remove_channel(self, channelname):
        del self.channels[irc_lower(channelname)]

    def change_nick(self, client, new):
        lower = irc_lower(new)
        if lower in self.nicks or lower in client.wechat_users:
            client.err_nicknameinuse(new)
        elif not Server.valid_nickname.match(new):
            client.err_errorneusnickname(new)
        else:
            if client.nick:
                info('%s changed nick to %s', client.prefix, new)
                self.remove_nick(client.nick)
                client.message_related(True, '{} NICK {}', client.prefix, new)
            self.nicks[lower] = client
            client.nick = new

    def has_nick(self, nick):
        return irc_lower(nick) in self.nicks

    def get_nick(self, nick):
        return self.nicks[irc_lower(nick)]

    def remove_nick(self, nick):
        del self.nicks[irc_lower(nick)]

    def change_token(self, client, new):
        if client.token == new:
            return True
        if new in self.tokens:
            return False
        if client.token:
            self.tokens.pop(client.token)
        self.tokens[new] = client
        client.token = new
        return True

    def start(self, loop):
        self.loop = loop
        self.server = loop.run_until_complete(asyncio.streams.start_server(
            self._accept, self.options.listen, self.options.port))

    def stop(self):
        self.server.close()
        self.loop.run_until_complete(self.server.wait_closed())

    ## WebSocket
    def on_wechat(self, data):
        token = data['token']
        if token in self.tokens:
            self.tokens[token].on_wechat(data)

    def on_wechat_open(self, token, peername):
        if token in self.tokens:
            self.tokens[token].on_wechat_open(peername)

    def on_wechat_close(self, token, peername):
        if token in self.tokens:
            self.tokens[token].on_wechat_close(peername)


def main():
    ap = ArgumentParser(description='wechatircd brings wx.qq.com to IRC clients')
    ap.add_argument('-q', '--quiet', action='store_const', const=logging.WARN, dest='loglevel')
    ap.add_argument('-v', '--verbose', action='store_const', const=logging.DEBUG, dest='loglevel')
    ap.add_argument('-t', '--tags', action='store_true', help='generate tags for wx.js')
    ap.add_argument('-d', '--debug', action='store_true', help='run ipdb on uncaught exception')
    ap.add_argument('-l', '--listen', default='127.0.0.1', help='IRC/HTTP/WebSocket listen address')
    ap.add_argument('-p', '--port', type=int, default=6667, help='IRC server listen port')
    ap.add_argument('--password', help='admin password')
    ap.add_argument('--heartbeat', type=int, default=30, help='time to wait for IRC commands. The server will send PING and close the connection after another timeout of equal duration if no commands is received.')
    ap.add_argument('--web-port', type=int, default=9000, help='HTTP/WebSocket listen port')
    ap.add_argument('--tls-cert', help='HTTP/WebSocket listen port')
    ap.add_argument('--tls-key', help='HTTP/WebSocket listen port')
    options = ap.parse_args()

    # send to syslog if run as a daemon (no controlling terminal)
    try:
        with open('/dev/tty'):
            pass
        logging.basicConfig(format='%(asctime)s:%(levelname)s: %(message)s')
    except OSError:
        logging.root.addHandler(logging.handlers.SysLogHandler('/dev/log'))
    logging.root.setLevel(options.loglevel or logging.INFO)

    if options.tls_cert:
        tls = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
        tls.load_cert_chain(options.tls_cert, options.tls_key)
    else:
        tls = None

    loop = asyncio.get_event_loop()
    if options.debug:
        sys.excepthook = ExceptionHook()
    server = Server(options)
    web = Web()

    server.start(loop)
    web.start(options.listen, options.web_port, tls, loop)
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        server.stop()
        web.stop()
        loop.stop()


if __name__ == '__main__':
    sys.exit(main())
