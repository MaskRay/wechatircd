#!/usr/bin/env python3
from argparse import ArgumentParser
from aiohttp import web
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
        Web.instance = self

    def remove_ws(self, ws):
        del self.token2ws[self.ws2token[ws]]
        del self.ws2token[ws]

    def remove_token(self, token):
        del self.ws2token[self.token2ws[token]]
        del self.token2ws[token]

    async def handle_webwxapp_js(self, request):
        return web.Response(body=self.webwxapp_js,
                            headers={'Content-Type': 'application/javascript; charset=UTF-8',
                                     'Access-Control-Allow-Origin': '*'})

    async def handle_web_socket(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        peername = request.transport.get_extra_info('peername')
        info('WebSocket connected to %r', peername)
        async for msg in ws:
            if msg.tp == web.MsgType.text:
                try:
                    data = json.loads(msg.data)
                    token = data['token']
                    assert isinstance(token, str) and re.match(r'^[0-9a-f]{32}$', token)
                    if ws in self.ws2token:
                        if self.ws2token[ws] != token:
                            self.remove_ws(ws)
                    if ws not in self.ws2token:
                        if token in self.token2ws:
                            self.remove_token(token)
                        self.ws2token[ws] = token
                        self.token2ws[token] = ws
                        Server.instance.on_wechat_open(token, peername)
                    Server.instance.on_wechat(data)
                except:
                    break
            elif msg.tp == web.MsgType.ping:
                try:
                    ws.pong()
                except:
                    break
            elif msg.tp == web.MsgType.close:
                break
        info('WebSocket disconnected from %r', peername)
        if t in self.ws2token:
            token = self.ws2token[t]
            self.remove_ws(t)
            Server.instance.on_wechat_close(token, peername)
        return ws

    def send(self, token, receiver, msg):
        if token in self.token2ws:
            ws = self.token2ws[token]
            try:
                ws.send_str(json.dumps({
                    'command': 'send_text_message',
                    'receiver': receiver,
                    'message': msg,
                    #@ webwxapp.js /e.ClientMsgId = e.LocalID = e.MsgId = (utilFactory.now() + Math.random().toFixed(3)).replace(".", ""),
                    'local_id': '{}0{:03}'.format(int(time.time()*1000), random.randint(0, 999)),
                }, ensure_ascii=False))
            except:
                pass

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

### IRC

def irc_lower(s):
    irc_trans = str.maketrans(string.ascii_uppercase+'[]\\^',
                              string.ascii_lowercase+'{}|~')
    return s.translate(irc_trans)


# loose
def irc_escape(s):
    s = re.sub(r',', '.', s)
    s = re.sub(r'<[^>]*>', '', s)
    return re.sub(r'[^-\w$%^*()=./]', '', s)


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
    def ison(client, *nicks):
        online = [nick for nick in nicks if client.server.get_nick(nick)]
        client.reply('303 :{}', ' '.join(online))

    @staticmethod
    def join(client, arg):
        if arg == '0':
            for channelname in client.channels:
                if client.part(channelname):
                    client.channels.pop(channelname)
        else:
            for channelname in arg.split(','):
                if not client.is_in_channel(channelname):
                    try:
                        channel = client.server.ensure_channel(channelname)
                        if channel.on_join(client):
                            client.channels[irc_lower(channelname)] = channel
                    except ValueError:
                        client.err_nosuchchannel(channelname)

    @staticmethod
    def lusers(client):
        client.reply('251 :There are {} users', len(client.server.nicks))

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
        for channelname in arg.split(','):
            client.part(channelname, args[0] if args else None)

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
        if args:
            msg = args[0]
        else:
            msg = client.prefix
        client.disconnect(msg)

    @staticmethod
    def who(client, target):
        if client.server.has_nick(target):
            # TODO
            pass
        elif client.is_in_channel(target):
            client.get_channel(target).who(client)
        elif client.server.has_channel(target):
            client.server.get_channel(client, target).who(client)

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
        # on name conflict, prefer to resolve WeChat friend first
        if client.has_wechat_user(target):
            user = client.get_wechat_user(target)
            if user.is_friend:
                Web.instance.send(client.token, user.username, msg)
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
                # server generated messages won't be received
                client.write(':{} PRIVMSG {} :{}'.format(
                    client.prefix, room.name, msg))
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


class Channel:
    def __init__(self, server, name):
        self.server = server
        self.name = name
        self.topic = ''
        self.members = set()

    def on_notice_or_privmsg(self, client, command, msg):
        self.on_event(client, command, '{} :{}'.format(self.name, msg))

    def on_event(self, source, command, msg, include_self=False):
        for client in self.members:
            if client != source or include_self:
                try:
                    client.write(':{} {} {}'.format(source.prefix, command, msg))
                except:
                    pass

    def on_join(self, client):
        if client in self.members:
            return False
        info('%s joined %s', client.prefix, self.name)
        self.members.add(client)
        self.on_event(client, 'JOIN', self.name, True)
        self.on_names(client)
        return True

    def on_names(self, client):
        client.reply('353 = {} :{}', self.name,
                     ' '.join(sorted(x.nick for x in self.members)))
        client.reply('366 {} :End of NAMES list', self.name)

    def on_part(self, client, msg):
        if client not in self.members:
            client.err_notonchannel(self.name)
            return False
        if msg:
            self.on_event(client, 'PART', msg, True)
        self.members.remove(client)
        if not self.members:
            self.server.remove_channel(self)
        return True

    def on_who(self, client):
        for member in self.members:
            client.reply('352 {} {} {} {} {} H :0 {}',
                            self.name, member.user, member.host, self.server.name,
                            member.nickname, member.realname)
            client.reply('315 {} :End of WHO list', self.name)


# A special channel where each client can only see himself
class StatusChannel(Channel):
    instance = None

    def __init__(self, server):
        super().__init__(server, '+status')
        self.shadow_members = weakref.WeakKeyDictionary()
        if not StatusChannel.instance:
            StatusChannel.instance = self

    @property
    def prefix(self):
        return self.name

    def respond(self, client, msg, *args):
        if args:
            client.write((':{} PRIVMSG {} :'+msg).format(self.name, self.name, *args))
        else:
            client.write((':{} PRIVMSG {} :').format(self.name, self.name)+msg)

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
                if isinstance(room, Channel):
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
            info('%s joined %s', member.prefix, self.name)
            self.members.add(member)
            self.on_event(member, member, 'JOIN', self.name)
            self.on_names(member)
        else:
            client = member.client
            if client not in self.shadow_members:
                self.shadow_members[client] = set()
            if member in self.shadow_members[client]:
                return False
            self.shadow_members[client].add(member)
            self.on_event(client, member, 'JOIN', self.name)
        return True

    def on_names(self, client):
        members = [x.nick for x in self.shadow_members.get(client, ())]
        members.append(client.nick)
        client.reply('353 = {} :{}', self.name, ' '.join(sorted(members)))
        client.reply('366 {} :End of NAMES list', self.name)

    def on_part(self, member, msg):
        if isinstance(member, Client):
            if member not in self.members:
                member.err_notonchannel(self.name)
                return False
            if msg:
                self.on_event(member, member, 'PART', msg)
            self.members.remove(member)
        else:
            client = member.client
            self.shadow_members[weakref.ref(client)].pop(member)
            self.on_event(client, member, 'PART', msg)
        return True

    def on_event(self, client, source, command, msg):
        try:
            client.write(':{} {} {}'.format(source.prefix, command, msg))
        except:
            pass


class WeChatRoom:
    def __init__(self, client, record):
        self.client = client
        self.username = record['UserName']
        self.record = {}
        self.joined = False   # JOIN event has not been emitted
        self.members = set()  # room members excluding `client`, used only for listing
        self.update(client, record)

    def update(self, client, record):
        self.record.update(record)
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
            if self.joined:
                self.on_event(client, 'PART', self.name)
            self.name = name
            if self.joined:
                self.on_event(client, 'JOIN', self.name)

    def update_members(self, client, members):
        seen = set()
        for member in members:
            user = client.ensure_wechat_user(member)
            seen.add(user)
            if user not in self.members:
                self.members.add(user)
                user.rooms.add(self)
                self.on_event(user, 'JOIN', self.name)
        for user in self.members - seen:
            self.members.remove(user)
            user.rooms.remove(self)
            self.on_event(user, 'PART', self.name)
        self.members = seen

    def on_notice_or_privmsg(self, client, command, msg):
        Web.instance.send(client.token, self.username, msg)

    def on_event(self, source, command, msg):
        if self.joined:
            try:
                self.client.write(':{} {} {}'.format(source.prefix, command, msg))
            except:
                pass

    def on_join(self, client):
        if self.joined:
            return False
        info('%s joined %s', client.prefix, self.name)
        self.joined = True
        self.on_event(client, 'JOIN', self.name)
        self.on_names(client)
        return True

    def on_names(self, client):
        members = tuple(x.nick for x in self.members)+(client.nick,)
        client.reply('353 = {} :{}', self.name, ' '.join(sorted(members)))
        client.reply('366 {} :End of NAMES list', self.name)

    def on_part(self, client, msg):
        if self.joined:
            self.joined = False
            return True
        return False


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
        self.channels = {}             # name -> IRC channel or WeChat chatroom
        self.username2wechat_room = {} # UserName -> WeChatRoom
        self.wechat_users = {}         # nick -> IRC user or WeChat user (friend or room contact)
        self.username2wechat_user = {} # UserName -> WeChatUser
        self.token = None

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
        self.channels.pop(irc_lower(channelname))

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
        self.message_related(False, ':{} QUIT :{}'.format(self.prefix, quitmsg))
        self.writer.write_eof()
        self.writer.close()
        for channel in self.channels.values():
            channel.on_part(self, None)

    def reply(self, msg, *args):
        self.write((':{} '+msg).format(self.server.name, *args))

    def write(self, msg):
        self.writer.write(msg.encode())
        self.writer.write(b'\n')

    @property
    def prefix(self):
        return '{}!{}@{}'.format(self.nick or '', self.user or '', self.host or '')

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

    def err_notonchannel(self, channelname):
        self.reply("442 {} :You're not on that channel", channelname)

    def err_needmoreparams(self, command):
        self.reply('461 {} :Not enough parameters', command)

    def part(self, channelname, msg=None):
        if not self.is_in_channel(channelname):
            self.err_notonchannel(channelname)
            return
        if self.get_channel(channelname).on_part(self, msg if msg else channelname):
            self.remove_channel(channelname)

    def message_related(self, include_self, msg):
        clients = set()
        for channel in self.channels.values():
            if isinstance(channel, Channel):
                clients |= channel.members
        if include_self:
            clients.add(self)
        else:
            clients.discard(self)
        for client in clients:
            client.write(msg)

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
                    self.reply('PING :{}', self.server.name)
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

    def on_wechat(self, data):
        command = data['command']
        if type(WeChatCommands.__dict__.get(command)) == staticmethod:
            getattr(WeChatCommands, command)(self, data)

    def on_wechat_open(self, peername):
        status = StatusChannel.instance
        status.on_event(self, status, 'NOTICE',
                        '{} :Connected to {}'.format(status.name, peername))

    def on_wechat_close(self, peername):
        self.wechat_users.clear()
        self.username2wechat_user.clear()
        for room in self.username2wechat_room.values():
            room.on_event(self, 'PART', room.name)
            self.remove_channel(room.name)
        self.username2wechat_room.clear()
        status = StatusChannel.instance
        status.on_event(self, status, 'NOTICE',
                        '{} :Disconnected from '.format(status.name, peername))


class WeChatUser:
    def __init__(self, client, record):
        self.client = client
        self.username = record['UserName']
        self.rooms = set()
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
            for room in self.rooms:
                self.client.write(':{} NICK {}'.format(self.prefix, nick))
            self.nick = nick
        if 'RemarkName' in self.record:
            if not self.is_friend:
                self.is_friend = True
                StatusChannel.instance.on_join(self)


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
        if not Server.instance:
            Server.instance = self

    def _accept(self, reader, writer):
        def done(task):
            if client.nick:
                self.nicks.pop(client.nick)
            if client.token:
                self.tokens.pop(client.token)

        try:
            client = Client(self, reader, writer)
            task = self.loop.create_task(client.handle_irc())
            task.add_done_callback(done)
        except Exception as e:
            traceback.print_exc()

    # IRC channel or WeChat chatroom
    def has_channel(self, channelname):
        return irc_lower(channelname) in self.channels

    # IRC channel or WeChat chatroom
    def ensure_channel(self, channelname):
        if self.has_channel(channelname):
            return self.channels[irc_lower(channelname)]
        if not Server.valid_channelname.match(channelname):
            raise ValueError
        channel = Channel(self, channelname)
        self.channels[irc_lower(channelname)] = channel
        return channel

    def remove_channel(self, channel):
        self.channels.pop(irc_lower(channel.name))

    def change_nick(self, client, new):
        lower = irc_lower(new)
        if lower in self.nicks or lower in client.wechat_users:
            client.err_nicknameinuse(new)
        elif not Server.valid_nickname.match(new):
            client.err_errorneusnickname(new)
        else:
            info('%s changed nick to %s', client.prefix, new)
            if client.nick:
                self.nicks.pop(irc_lower(client.nick))
            self.nicks[lower] = client
            client.nick = new

    def has_nick(self, nick):
        return irc_lower(nick) in self.nicks

    def get_nick(self, nick):
        return self.nicks[irc_lower(nick)]

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
    ap = ArgumentParser()
    ap.add_argument('-q', '--quiet', action='store_const', const=logging.WARN, dest='loglevel')
    ap.add_argument('-v', '--verbose', action='store_const', const=logging.DEBUG, dest='loglevel')
    ap.add_argument('-t', '--tags', action='store_true', help='generate tags for wx.js')
    ap.add_argument('-d', '--debug', action='store_true', help='run ipdb on uncaught exception')
    ap.add_argument('-l', '--listen', default='127.0.0.1', help='listen address')
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
