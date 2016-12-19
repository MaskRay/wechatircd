#!/usr/bin/env python3
from argparse import ArgumentParser, Namespace
from aiohttp import web
#from ipdb import set_trace as bp
from datetime import datetime, timezone
import aiohttp, asyncio, inspect, json, logging.handlers, os, pprint, random, re, \
    signal, socket, ssl, string, sys, time, traceback, uuid, weakref

logger = logging.getLogger('wechatircd')
im_name = 'WeChat'


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


### HTTP serving js & WebSocket server

class Web(object):
    instance = None

    def __init__(self, http_root):
        self.http_root = http_root
        self.ws = weakref.WeakSet()
        assert not Web.instance
        Web.instance = self

    async def handle_index(self, request):
        with open(os.path.join(self.http_root, 'index.html'), 'rb') as f:
            return web.Response(body=f.read())

    async def handle_app_js(self, request):
        with open(os.path.join(self.http_root, 'webwxapp.js'), 'rb') as f:
            return web.Response(body=f.read(),
                                headers={'Content-Type': 'application/javascript; charset=UTF-8',
                                         'Access-Control-Allow-Origin': '*'})
    async def handle_injector_js(self, request):
        with open(os.path.join(self.http_root, 'injector.js'), 'rb') as f:
            return web.Response(body=f.read(),
                                headers={'Content-Type': 'application/javascript; charset=UTF-8',
                                         'Access-Control-Allow-Origin': '*'})

    async def handle_web_socket(self, request):
        ws = web.WebSocketResponse()
        self.ws.add(ws)
        peername = request.transport.get_extra_info('peername')
        info('WebSocket client connected from %r', peername)
        await ws.prepare(request)
        async for msg in ws:
            if msg.tp == web.MsgType.text:
                try:
                    data = json.loads(msg.data)
                    Server.instance.on_websocket(data)
                except AssertionError:
                    info('WebSocket client error')
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
        info('WebSocket client disconnected from %r', peername)
        for client in Server.instance.clients:
            client.on_websocket_close(peername)
        return ws

    def start(self, listens, port, tls, loop):
        self.loop = loop
        self.app = aiohttp.web.Application()
        self.app.router.add_route('GET', '/', self.handle_index)
        self.app.router.add_route('GET', '/webwxapp.js', self.handle_app_js)
        self.app.router.add_route('GET', '/injector.js', self.handle_injector_js)
        self.app.router.add_route('GET', '/ws', self.handle_web_socket)
        self.handler = self.app.make_handler()
        self.srv = []
        for i in listens:
            self.srv.append(loop.run_until_complete(
                loop.create_server(self.handler, i, port, ssl=tls)))

    def stop(self):
        for i in self.srv:
            i.close()
            self.loop.run_until_complete(i.wait_closed())
        self.loop.run_until_complete(self.app.shutdown())
        self.loop.run_until_complete(self.handler.finish_connections(0))
        self.loop.run_until_complete(self.app.cleanup())

    def close_connections(self):
        for ws in self.ws:
            ws.send_str(json.dumps({'command': 'close'}))

    def send_file(self, receiver, filename, body):
        for ws in self.ws:
            try:
                body = body.decode('latin-1')
                ws.send_str(json.dumps({
                    'command': 'send_file',
                    'receiver': receiver,
                    'filename': filename,
                    'body': body,
                }))
            except:
                pass
            break

    def send_text_message(self, receiver, msg):
        for ws in self.ws:
            try:
                ws.send_str(json.dumps({
                    'command': 'send_text_message',
                    'receiver': receiver,
                    'message': msg,
                }))
            except:
                pass

    def add_friend(self, username, message):
        for ws in self.ws:
            try:
                ws.send_str(json.dumps({
                    'command': 'add_friend',
                    'user': username,
                    'message': message,
                }))
            except:
                pass
            break

    def add_member(self, roomname, username):
        for ws in self.ws:
            try:
                ws.send_str(json.dumps({
                    'command': 'add_member',
                    'room': roomname,
                    'user': username,
                }))
            except:
                pass
            break

    def del_member(self, roomname, username):
        for ws in self.ws:
            try:
                ws.send_str(json.dumps({
                    'command': 'del_member',
                    'room': roomname,
                    'user': username,
                }))
            except:
                pass
            break

    def mod_topic(self, roomname, topic):
        for ws in self.ws:
            try:
                ws.send_str(json.dumps({
                    'command': 'mod_topic',
                    'room': roomname,
                    'topic': topic,
                }))
            except:
                pass
            break

    def reload_friend(self, who):
        for ws in self.ws:
            try:
                ws.send_str(json.dumps({
                    'command': 'reload_friend',
                    'name': who,
                }))
            except:
                pass
            break

    def web_eval(self, expr):
        for ws in self.ws:
            try:
                ws.send_str(json.dumps({
                    'command': 'eval',
                    'expr': expr,
                }))
            except:
                pass
            break

### IRC utilities

def irc_lower(s):
    irc_trans = str.maketrans(string.ascii_uppercase + '[]\\^',
                              string.ascii_lowercase + '{}|~')
    return s.translate(irc_trans)


# loose
def irc_escape(s):
    s = re.sub(r',', '.', s)       # `,` is used as seprator in IRC messages
    s = re.sub(r'&amp;?', '', s)   # chatroom name may include `&`
    s = re.sub(r'<[^>]*>', '', s)  # remove emoji
    return re.sub(r'[^-\w$%^*()=./]', '', s)

### Commands

class UnregisteredCommands(object):
    @staticmethod
    def cap(client, *args):
        if not args: return
        comm = args[0].lower()
        if comm == 'ls' or comm == 'list':
            client.reply('CAP * {} :server-time', args[0])
        elif comm == 'req':
            client.capabilities = set(['server-time']) & set(args[1].split())
            client.reply('CAP * ACK :{}', ' '.join(client.capabilities))

    @staticmethod
    def nick(client, *args):
        if len(client.server.options.irc_password) and not client.authenticated:
            client.err_passwdmismatch('NICK')
            return
        if not args:
            client.err_nonicknamegiven()
            return
        client.server.change_nick(client, args[0])

    @staticmethod
    def pass_(client, password):
        if len(client.server.options.irc_password) and password == client.server.options.irc_password:
            client.authenticated = True

    @staticmethod
    def quit(client):
        client.disconnect('Client quit')

    @staticmethod
    def user(client, user, mode, _, realname):
        if len(client.server.options.irc_password) and not client.authenticated:
            client.err_passwdmismatch('USER')
            return
        client.user = user
        client.realname = realname


class RegisteredCommands:
    @staticmethod
    def away(client):
        pass

    @staticmethod
    def cap(client, *args):
        UnregisteredCommands.cap(client, *args)

    @staticmethod
    def info(client):
        client.rpl_info('{} users', len(client.server.nicks))
        client.rpl_info('{} {} users', im_name, len(client.nick2special_user))
        client.rpl_info('{} {} friends', im_name,
                        len(StatusChannel.instance.shadow_members.get(client, {})))
        client.rpl_info('{} {} rooms', im_name, len(client.name2special_room))

    @staticmethod
    def invite(client, nick, channelname):
        if client.is_in_channel(channelname):
            client.get_channel(channelname).on_invite(client, nick)
        else:
            client.err_notonchannel(channelname)

    @staticmethod
    def ison(client, *nicks):
        client.reply('303 {} :{}', client.nick,
                     ' '.join(nick for nick in nicks
                              if client.has_special_user(nick) or
                              client.server.has_nick(nick)))

    @staticmethod
    def join(client, arg):
        if arg == '0':
            channels = list(client.channels.values())
            for channel in channels:
                channel.on_part(client, channel.name)
        else:
            for channelname in arg.split(','):
                if client.has_special_room(channelname):
                    client.get_special_room(channelname).on_join(client)
                else:
                    try:
                        client.server.ensure_channel(channelname).on_join(client)
                    except ValueError:
                        client.err_nosuchchannel(channelname)

    @staticmethod
    def kick(client, channelname, nick, reason=None):
        if client.is_in_channel(channelname):
            client.get_channel(channelname).on_kick(client, nick, reason)
        else:
            client.err_notonchannel(channelname)

    @staticmethod
    def list(client, arg=None):
        if arg:
            channels = [client.get_channel(channelname)
                        for channelname in arg.split(',')
                        if client.has_channel(channelname) or
                        client.has_special_room(channelname)]
        else:
            channels = set(client.channels.values())
            for channel in client.name2special_room.values():
                channels.add(channel)
            channels = list(channels)
        channels.sort(key=lambda ch: ch.name)
        for channel in channels:
            client.reply('322 {} {} {} :{}', client.nick, channel.name,
                         channel.n_members(client), channel.topic)
        client.reply('323 {} :End of LIST', client.nick)

    @staticmethod
    def lusers(client):
        client.reply('251 :There are {} users and {} {} users (local to you) on 1 server',
                     len(client.server.nicks),
                     len(client.nick2special_user),
                     im_name
                     )

    @staticmethod
    def mode(client, target, *args):
        if client.has_special_user(target):
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
        elif client.has_special_room(target):
            client.get_special_room(target).on_mode(client)
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
    def stats(client, query):
        if len(query) == 1:
            if query == 'u':
                td = datetime.now() - client.server._boot
                client.reply('242 {} :Server Up {} days {}:{:02}:{:02}',
                             client.nick, td.days, td.seconds // 3600,
                             td.seconds // 60 % 60, td.seconds % 60)
            client.reply('219 {} {} :End of STATS report', client.nick, query)

    @staticmethod
    def summon(client, nick, msg):
        if client.has_special_user(nick):
            Web.instance.add_friend(client.get_special_user(nick).username, msg)
        else:
            client.err_nologin(nick)

    @staticmethod
    def time(client):
        client.reply('391 {} {} :{}Z', client.nick, client.server.name,
                     datetime.utcnow().isoformat())

    @staticmethod
    def topic(client, channelname, new=None):
        if not client.is_in_channel(channelname):
            client.err_notonchannel(channelname)
            return
        client.get_channel(channelname).on_topic(client, new)

    @staticmethod
    def who(client, target):
        if client.has_special_user(target):
            client.get_special_user(target).on_who_member(
                client, StatusChannel.instance.name)
        elif client.server.has_nick(target):
            client.server.get_nick(target).on_who_member(
                client, client.server.name)
        elif client.is_in_channel(target):
            client.get_channel(target).on_who(client)
        client.reply('315 {} {} :End of WHO list', client.nick, target)

    @staticmethod
    def whois(client, *args):
        if not args:
            client.err_nonicknamegiven()
            return
        elif len(args) == 1:
            target = args[0]
        else:
            target = args[1]
        if client.has_special_user(target):
            client.get_special_user(target).on_whois(client)
        elif client.server.has_nick(target):
            client.server.get_nick(target).on_whois(client)
        else:
            client.err_nosuchnick(target)
            return
        client.reply('318 {} {} :End of WHOIS list', client.nick, target)

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
        # on name conflict, prefer to resolve special user first
        if client.has_special_user(target):
            user = client.get_special_user(target)
            if user.is_friend:
                user.on_notice_or_privmsg(client, command, msg)
            elif command == 'PRIVMSG':
                client.err_nosuchnick(target)
        # then IRC nick
        elif client.server.has_nick(target):
            client2 = client.server.get_nick(target)
            client2.write(':{} {} {} :{}'.format(
                client.prefix, 'PRIVMSG', target, msg))
        # IRC channel or special chatroom
        elif client.is_in_channel(target):
            client.get_channel(target).on_notice_or_privmsg(
                client, command, msg)
        elif command == 'PRIVMSG':
            client.err_nosuchnick(target)


class SpecialCommands:
    @staticmethod
    def add_friend_ack(client, data):
        nick = client.username2special_user[data['user']].nick
        client.reply('342 {} {} :Summoning user to IRC', client.nick, nick)

    @staticmethod
    def add_friend_nak(client, data):
        nick = client.username2special_user[data['user']].nick
        client.status('Friend request to {} failed'.format(nick))

    @staticmethod
    def friend(client, data):
        record = data['record']
        debug('friend: ' + ', '.join([k + ':' + repr(record.get(k)) for k in ['DisplayName', 'NickName', 'UserName']]))
        client.ensure_special_user(record, 1)

    @staticmethod
    def message(client, data):
        client.ensure_special_user(data['receiver']).on_websocket_message(data)

    @staticmethod
    def room_contact(client, data):
        record = data['record']
        debug('room_contact: ' + ', '.join([k + ':' + repr(record.get(k)) for k in ['DisplayName', 'NickName', 'UserName']]))
        client.ensure_special_user(data['record'], -1)

    @staticmethod
    def room(client, data):
        record = data['record']
        debug('room: ' + ', '.join(k + ':' + repr(record.get(k)) for k in ['DisplayName', 'NickName', 'UserName']))
        client.ensure_special_room(record).update_detail(record)

    @staticmethod
    def room_message(client, data):
        client.ensure_special_room(data['receiver']).on_websocket_message(data)

    @staticmethod
    def self(client, data):
        client.username = data['UserName']

    @staticmethod
    def send_file_message_nak(client, data):
        receiver = data['receiver']
        filename = data['filename']
        if client.has_special_room(receiver):
            room = client.get_special_room(receiver)
            client.write(':{} PRIVMSG {} :[文件发送失败] {}'.format(
                client.prefix, room.nick, filename))
        elif client.has_special_user(receiver):
            user = client.get_special_user(receiver)
            client.write(':{} PRIVMSG {} :[文件发送失败] {}'.format(
                client.prefix, user.nick, filename))


    @staticmethod
    def send_text_message_nak(client, data):
        receiver = data['receiver']
        msg = data['message']
        if client.has_special_room(receiver):
            room = client.get_special_room(receiver)
            client.write(':{} PRIVMSG {} :[文字发送失败] {}'.format(
                client.prefix, room.nick, msg))
        elif client.has_special_user(receiver):
            user = client.get_special_user(receiver)
            client.write(':{} PRIVMSG {} :[文字发送失败] {}'.format(
                client.prefix, user.nick, msg))

    @staticmethod
    def web_debug(client, data):
        debug('web_debug: ' + repr(data))

### Channels: StandardChannel, StatusChannel, SpecialChannel

class Channel:
    def __init__(self, name):
        self.name = name
        self.topic = ''
        self.mode = 'n'
        self.members = {}

    @property
    def prefix(self):
        return self.name

    def log(self, source, fmt, *args):
        info('%s %s '+fmt, self.name, source.nick, *args)

    def multicast_group(self, source):
        raise NotImplemented

    def n_members(self, client):
        return len(self.members)

    def event(self, source, command, fmt, *args, include_source=True):
        line = fmt.format(*args) if args else fmt
        for client in self.multicast_group(source):
            if client != source or include_source:
                client.write(':{} {} {}'.format(source.prefix, command, line))

    def dehalfop_event(self, user):
        self.event(self, 'MODE', '{} -h {}', self.name, user.nick)

    def deop_event(self, user):
        self.event(self, 'MODE', '{} -o {}', self.name, user.nick)

    def devoice_event(self, user):
        self.event(self, 'MODE', '{} -v {}', self.name, user.nick)

    def halfop_event(self, user):
        self.event(self, 'MODE', '{} +h {}', self.name, user.nick)

    def nick_event(self, user, new):
        self.event(user, 'NICK', new)

    def join_event(self, user):
        self.event(user, 'JOIN', self.name)

    def kick_event(self, kicker, channel, kicked, reason=None):
        if reason:
            self.event(kicker, 'KICK', '{} {}: {}', channel.name, kicked.nick, reason)
        else:
            self.event(kicker, 'KICK', '{} {}', channel.name, kicked.nick)
        self.log(kicker, 'kicked %s', kicked.prefix)

    def op_event(self, user):
        self.event(self, 'MODE', '{} +o {}', self.name, user.nick)

    def part_event(self, user, partmsg):
        if partmsg:
            self.event(user, 'PART', '{} :{}', self.name, partmsg)
        else:
            self.event(user, 'PART', self.name)

    def voice_event(self, user):
        self.event(user, 'MODE', '{} +v {}', self.name, user.nick)

    def on_invite(self, client, nick):
        # TODO
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

    def on_names(self, client):
        members = []
        for u, mode in self.members.items():
            nick = u.nick
            if 'o' in mode:
                nick = '@'+nick
            elif 'v' in mode:
                nick = '+'+nick
            members.append(nick)
        if members:
            client.reply('353 {} = {} :{}', client.nick, self.name,
                         ' '.join(sorted(members)))
        client.reply('366 {} {} :End of NAMES list', client.nick, self.name)

    def on_topic(self, client, new=None):
        if new:
            client.err_nochanmodes(self.name)
        else:
            if self.topic:
                client.reply('332 {} {} :{}', client.nick, self.name, self.topic)
            else:
                client.reply('331 {} {} :No topic is set', client.nick, self.name)


class StandardChannel(Channel):
    def __init__(self, server, name):
        super().__init__(name)
        self.server = server

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

    def on_part(self, client, msg=None):
        if client not in self.members:
            client.err_notonchannel(self.name)
            return False
        if msg:  # explicit PART, not disconnection
            self.part_event(client, msg)
        if len(self.members) == 1:
            self.server.remove_channel(self.name)
        elif 'o' in self.members.pop(client):
            user = next(iter(self.members))
            self.members[user] += 'o'
            self.op_event(user)
        client.leave(self)
        return True

    def on_topic(self, client, new=None):
        if new:
            self.log(client, 'set topic %r', new)
            self.topic = new
            self.event(client, 'TOPIC', '{} :{}', self.name, new)
        else:
            super().on_topic(client, new)

    def on_who(self, client):
        for member in self.members:
            member.on_who_member(client, self.name)


# A special channel where each client can only see himself
class StatusChannel(Channel):
    instance = None

    def __init__(self, server):
        super().__init__('+wechat')
        self.server = server
        self.topic = "Your friends are listed here. Messages wont't be broadcasted to them. Type 'help' to see available commands"
        self.shadow_members = weakref.WeakKeyDictionary()
        assert not StatusChannel.instance
        StatusChannel.instance = self

    def multicast_group(self, source):
        client = source.client \
            if isinstance(source, (SpecialUser, SpecialChannel)) \
            else source
        return (client,) if client in self.members else ()

    def n_members(self, client):
        return len(self.shadow_members.get(client, {})) + \
            (1 if client in self.members else 0)

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
            self.respond(client, 'help')
            self.respond(client, '    display this help')
            self.respond(client, 'eval [password] expression')
            self.respond(client, '    eval python expression')
            self.respond(client, 'status [pattern]')
            self.respond(client, '    show status for user, channel and wechat rooms')
            self.respond(client, 'reload_friend $name')
            self.respond(client, '    reload friend info in case of no such nick/channel in privmsg, and use __all__ as name if you want to reload all')
        elif msg.startswith('status'):
            pattern = None
            ary = msg.split(' ', 1)
            if len(ary) > 1:
                pattern = ary[1]
            self.respond(client, 'IRC channels:')
            for name, room in client.channels.items():
                if pattern is not None and pattern not in name: continue
                if isinstance(room, StandardChannel):
                    self.respond(client, '    ' + name)
            self.respond(client, '{} Friends:', im_name)
            for name, user in client.nick2special_user.items():
                if user.is_friend:
                    if pattern is not None and not (pattern in name or pattern in user.record.get('DisplayName', '') or pattern in user.record.get('NickName','')): continue
                    line = name + ': friend ('
                    line += ', '.join([k + ':' + repr(v) for k, v in user.record.items() if k in ['DisplayName', 'NickName']])
                    line += ')'
                    self.respond(client, '    ' + line)
            self.respond(client, '{} Rooms:', im_name)
            for name, room in client.channels.items():
                if pattern is not None and pattern not in name: continue
                if isinstance(room, SpecialChannel):
                    self.respond(client, '    ' + name)
        elif msg.startswith('reload_friend'):
            who = None
            ary = msg.split(' ', 1)
            if len(ary) > 1:
                who = ary[1]
            if not who:
                self.respond(client, 'reload_friend <name>')
            else:
                Web.instance.reload_friend(who)
        elif msg.startswith('web_eval'):
            expr = None
            ary = msg.split(' ', 1)
            if len(ary) > 1:
                expr = ary[1]
            if not expr:
                self.respond(client, 'None')
            else:
                Web.instance.web_eval(expr)
                self.respond(client, 'expr sent, please use debug log to view eval result')
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
                self.respond(client, 'Unknown command {}', msg)

    def on_join(self, member):
        if isinstance(member, Client):
            if member in self.members:
                return False
            self.members[member] = ''
            super().on_join(member)
        else:
            client = member.client
            if client not in self.shadow_members:
                self.shadow_members[client] = {}
            if member in self.shadow_members[client]:
                return False
            member.enter(self)
            self.join_event(member)
            self.shadow_members[client][member] = ''
        return True

    def on_names(self, client):
        members = []
        if client in self.members:
            members.append(client.nick)
        for u, mode in self.shadow_members.get(client, {}).items():
            nick = u.nick
            if 'o' in mode:
                nick = '@'+nick
            elif 'v' in mode:
                nick = '+'+nick
            members.append(nick)
        client.reply('353 {} = {} :{}', client.nick, self.name, ' '.join(sorted(members)))
        client.reply('366 {} {} :End of NAMES list', client.nick, self.name)

    def on_part(self, member, msg=None):
        if isinstance(member, Client):
            if member not in self.members:
                member.err_notonchannel(self.name)
                return False
            if msg:  # explicit PART, not disconnection
                self.part_event(member, msg)
            del self.members[member]
        else:
            if member not in self.shadow_members.get(member.client, {}):
                return False
            self.part_event(member, msg)
            self.shadow_members[member.client].remove(member)
        member.leave(self)
        return True

    def on_who(self, client):
        if client in self.members:
            client.on_who_member(client, self.name)


class SpecialChannel(Channel):
    def __init__(self, client, record):
        super().__init__(None)
        self.client = client
        self.username = record['UserName']
        self.record = {}
        self.idle = True      # no messages yet
        self.joined = False   # `client` has not joined
        # For large chatrooms, record['MemberList']['Uin'] is very likely
        # to be 0, so the owner is hard to determine.
        # If the owner is determined, he/she is the only op
        self.update(client, record)
        self.log_file = None

    @property
    def nick(self):
        return self.name

    def update(self, client, record):
        self.record.update(record)
        self.topic = record['DisplayName']
        old_name = getattr(self, 'name', None)
        base = '&' + irc_escape(self.topic)
        if base == '&':
            base += '.'.join(member.nick for member in self.members)[:20]
        suffix = ''
        while 1:
            name = base+suffix
            if name == old_name or not client.server.has_channel(base+suffix):
                break
            suffix = str(int(suffix or 0)+1)
        if name != old_name:
            # PART -> rename -> JOIN to notify the IRC client
            joined = self.joined
            if joined:
                self.on_part(client, 'Changing name')
            self.name = name
            if joined:
                self.on_join(client)

    def update_detail(self, record):
        if isinstance(record.get('MemberList'), list):
            owner_uin = record.get('OwnerUin', -1)
            seen = {self.client: ''}
            for member in record['MemberList']:
                user = self.client.ensure_special_user(member)
                if user is not self.client:
                    if owner_uin > 0 and owner_uin == user.uin:
                        seen[user] = 'o'
                    elif user.is_friend:
                        seen[user] = 'v'
                    else:
                        seen[user] = ''
            for user in self.members.keys() - seen.keys():
                self.on_part(user, self.name)
            for user in seen.keys() - self.members.keys():
                if user is not self.client:
                    self.on_join(user)
            for user, mode in seen.items():
                old = self.members.get(user, '')
                if 'h' in old and 'h' not in mode:
                    self.dehalfop_event(user)
                if 'h' not in old and 'h' in mode:
                    self.halfop_event(user)
                if 'o' in old and 'o' not in mode:
                    self.deop_event(user)
                if 'o' not in old and 'o' in mode:
                    self.op_event(user)
                if 'v' in old and 'v' not in mode:
                    self.devoice_event(user)
                if 'v' not in old and 'v' in mode:
                    self.voice_event(user)
            self.members = seen

    def multicast_group(self, source):
        if not self.joined:
            return ()
        if isinstance(source, (SpecialUser, SpecialChannel)):
            return (source.client,)
        return (source,)

    def on_notice_or_privmsg(self, client, command, msg):
        if not client.ctcp(self.username, command, msg):
            client.server.irc_log(self, datetime.now(), client, msg)
            Web.instance.send_text_message(self.username, msg)

    def on_invite(self, client, nick):
        if client.has_special_user(nick):
            user = client.get_special_user(nick)
            if user in self.members:
                client.err_useronchannel(nick, self.name)
            elif not user.is_friend:
                client.err_nosuchnick(nick)
            else:
                Web.instance.add_member(self.username, user.username)
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
            self.members[member] = ''
            member.enter(self)
            self.join_event(member)
        return True

    def on_kick(self, client, nick, reason):
        if client.has_special_user(nick):
            user = client.get_special_user(nick)
            Web.instance.del_member(self.username, user.username)
        else:
            client.err_usernotinchannel(nick, self.name)

    def on_part(self, member, msg=None):
        if isinstance(member, Client):
            if not self.joined:
                member.err_notonchannel(self.name)
                return False
            if msg:  # not msg implies being disconnected/kicked/...
                self.part_event(member, msg)
            self.joined = False
        else:
            if member not in self.members:
                return False
            self.part_event(member, msg)
            del self.members[member]
        member.leave(self)
        return True

    def on_topic(self, client, new=None):
        if new:
            if True:  # TODO is owner
                Web.instance.mod_topic(self.username, new)
            else:
                client.err_nochanmodes(self.name)
        else:
            super().on_topic(client, new)

    def on_who(self, client):
        members = tuple(self.members)+(client,)
        for member in members:
            member.on_who_member(client, self.name)

    def on_websocket_message(self, data):
        msg = data['message']
        if self.idle:
            self.idle = False
            if self.client.options.join == 'auto' and not self.joined:
                self.client.auto_join(self)
        if not self.joined:
            return
        sender = self.client.ensure_special_user(data['sender'])
        if not sender:
            return
        if sender not in self.members:
            self.on_join(sender)
        for line in msg.splitlines():
            self.client.server.irc_log(self, datetime.fromtimestamp(data['time']), sender, line)
            if 'server-time' in self.client.capabilities:
                self.client.write('@time={}Z :{} PRIVMSG {} :{}'.format(
                    datetime.fromtimestamp(data['time'], timezone.utc).strftime('%FT%T.%f')[:23],
                    sender.prefix, self.name, line))
            else:
                self.client.write(':{} PRIVMSG {} :{}'.format(
                    sender.prefix, self.name, line))


class Client:
    def __init__(self, server, reader, writer, options):
        self.server = server
        self.options = Namespace()
        for k in ['heartbeat', 'ignore', 'ignore_display_name', 'join', 'dcc_send']:
            setattr(self.options, k, getattr(options, k))
        self.reader = reader
        self.writer = writer
        peer = writer.get_extra_info('socket').getpeername()
        self.host = peer[0]
        self.user = None
        self.nick = None
        self.registered = False
        self.mode = ''
        self.channels = {}               # joined, name -> channel
        self.name2special_room = {}      # name -> WeChat chatroom
        self.username2special_room = {}  # UserName -> SpecialChannel
        self.nick2special_user = {}      # nick -> IRC user or WeChat user (friend or room contact)
        self.username2special_user = {}  # UserName -> SpecialUser
        self.uin = 0
        self.username = ''
        self.capabilities = set()
        self.authenticated = False

    def enter(self, channel):
        self.channels[irc_lower(channel.name)] = channel

    def leave(self, channel):
        del self.channels[irc_lower(channel.name)]

    def auto_join(self, room):
        for regex in self.options.ignore or []:
            if re.search(regex, room.name):
                return
        for regex in self.options.ignore_display_name or []:
            if re.search(regex, room.topic):
                return
        room.on_join(self)

    def has_special_user(self, nick):
        return irc_lower(nick) in self.nick2special_user

    def has_special_room(self, name):
        return irc_lower(name) in self.name2special_room

    def get_special_user(self, nick):
        return self.nick2special_user[irc_lower(nick)]

    def get_special_room(self, name):
        return self.name2special_room[irc_lower(name)]

    def remove_special_user(self, nick):
        del self.nick2special_user[irc_lower(nick)]

    def ensure_special_user(self, record, friend=0):
        assert isinstance(record['UserName'], str)
        assert isinstance(record.get('DisplayName', ''), str)
        assert isinstance(record.get('Uin', 0), int)
        if record['UserName'] == self.username:
            uin = record.get('Uin', 0)
            if uin:
                self.uin = uin
            return self
        if record['UserName'] in self.username2special_user:
            user = self.username2special_user[record['UserName']]
            self.remove_special_user(user.nick)
            user.update(self, record, friend)
        else:
            user = SpecialUser(self, record, friend)
            self.username2special_user[user.username] = user
        self.nick2special_user[irc_lower(user.nick)] = user
        return user

    def is_in_channel(self, name):
        return irc_lower(name) in self.channels

    def get_channel(self, channelname):
        return self.channels[irc_lower(channelname)]

    def remove_channel(self, channelname):
        del self.channels[irc_lower(channelname)]

    def ensure_special_room(self, record):
        assert isinstance(record['UserName'], str)
        assert isinstance(record['DisplayName'], str)
        assert isinstance(record.get('OwnerUin', -1), int)
        if record['UserName'] in self.username2special_room:
            room = self.username2special_room[record['UserName']]
            del self.name2special_room[irc_lower(room.name)]
            room.update(self, record)
        else:
            room = SpecialChannel(self, record)
            self.username2special_room[room.username] = room
            if self.options.join == 'all':
                self.auto_join(room)
        self.name2special_room[irc_lower(room.name)] = room
        return room

    def disconnect(self, quitmsg):
        self.write('ERROR :{}'.format(quitmsg))
        info('Disconnected from %s', self.prefix)
        self.message_related(False, ':{} QUIT :{}', self.prefix, quitmsg)
        self.writer.write_eof()
        self.writer.close()
        channels = list(self.channels.values())
        for channel in channels:
            channel.on_part(self, None)

    def reply(self, msg, *args):
        '''Respond to the client's request'''
        self.write((':{} '+msg).format(self.server.name, *args))

    def write(self, msg):
        try:
            self.writer.write(msg.encode()+b'\n')
        except:
            pass

    def status(self, msg):
        '''A status message from the server'''
        self.write(':{} NOTICE {} :{}'.format(self.server.name, self.server.name, msg))

    @property
    def prefix(self):
        return '{}!{}@{}'.format(self.nick or '', self.user or '', self.host or '')

    def rpl_umodeis(self, mode):
        self.reply('221 {} +{}', self.nick, mode)

    def rpl_channelmodeis(self, channelname, mode):
        self.reply('324 {} {} +{}', self.nick, channelname, mode)

    def rpl_endofnames(self, channelname):
        self.reply('366 {} {} :End of NAMES list', self.nick, channelname)

    def rpl_info(self, fmt, *args):
        line = fmt.format(*args) if args else fmt
        self.reply('371 {} :{}', self.nick, line)

    def rpl_endofinfo(self, msg):
        self.reply('374 {} :End of INFO list', self.nick)

    def err_nosuchnick(self, name):
        self.reply('401 {} {} :No such nick/channel', self.nick, name)

    def err_nosuchserver(self, name):
        self.reply('402 {} {} :No such server', self.nick, name)

    def err_nosuchchannel(self, channelname):
        self.reply('403 {} {} :No such channel', self.nick, channelname)

    def err_noorigin(self):
        self.reply('409 {} :No origin specified', self.nick)

    def err_norecipient(self, command):
        self.reply('411 {} :No recipient given ({})', self.nick, command)

    def err_notexttosend(self):
        self.reply('412 {} :No text to send', self.nick)

    def err_unknowncommand(self, command):
        self.reply('421 {} {} :Unknown command', self.nick, command)

    def err_nonicknamegiven(self):
        self.reply('431 {} :No nickname given', self.nick)

    def err_errorneusnickname(self, nick):
        self.reply('432 * {} :Erroneous nickname', nick)

    def err_nicknameinuse(self, nick):
        self.reply('433 * {} :Nickname is already in use', nick)

    def err_usernotinchannel(self, nick, channelname):
        self.reply("441 {} {} {} :They are't on that channel", self.nick, nick, channelname)

    def err_notonchannel(self, channelname):
        self.reply("442 {} {} :You're not on that channel", self.nick, channelname)

    def err_useronchannel(self, nick, channelname):
        self.reply('443 {} {} {} :is already on channel', self.nick, nick, channelname)

    def err_nologin(self, nick):
        self.reply('444 {} {} :User not logged in', self.nick, nick)

    def err_needmoreparams(self, command):
        self.reply('461 {} {} :Not enough parameters', self.nick, command)

    def err_passwdmismatch(self, command):
        self.reply('464 * {} :Password incorrect', command)

    def err_nochanmodes(self, channelname):
        self.reply("477 {} {} :Channel doesn't support modes", self.nick, channelname)

    def err_chanoprivsneeded(self, channelname):
        self.reply("482 {} {} :You're not channel operator", self.nick, channelname)

    def err_umodeunknownflag(self):
        self.reply('501 {} :Unknown MODE flag', self.nick)

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
        if cmd == 'pass':
            cmd = cmd+'_'
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
                    status_channel.respond(self, 'Visit wx.qq.com and then you will see your friend list in this channel')
                    Web.instance.close_connections()

    async def handle_irc(self):
        sent_ping = False
        while 1:
            try:
                line = await asyncio.wait_for(
                    self.reader.readline(), loop=self.server.loop,
                    timeout=self.options.heartbeat)
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

    def ctcp(self, receiver, command, msg):
        async def download():
            reader, writer = await asyncio.open_connection(ip, port)
            body = b''
            while 1:
                # TODO timeout
                buf = await reader.read(size-len(body))
                if not buf:
                    break
                body += buf
                if len(body) >= size:
                    break
            Web.instance.send_file(receiver, filename, body)

        async def download_wrap():
            try:
                await asyncio.wait_for(download(), self.options.dcc_send_download_timeout)
            except asyncio.TimeoutError:
                self.status('Downloading of DCC SEND timeout')

        if command == 'PRIVMSG' and len(msg) > 2 and msg[0] == '\1' and msg[-1] == '\1':
            # VULNERABILITY used as proxy
            try:
                dcc_, send_, filename, ip, port, size = msg[1:-1].split(' ')
                ip = socket.gethostbyname(str(int(ip)))
                size = int(size)
                assert dcc_ == 'DCC' and send_ == 'SEND'
                if 0 < size <= self.options.dcc_send:
                    self.server.loop.create_task(download())
                else:
                    self.status('DCC SEND: invalid size of {}, (0,{}] is acceptable'.format(
                            filename, self.options.dcc_send))
            except:
                pass
            return True
        return False

    def on_who_member(self, client, channelname):
        client.reply('352 {} {} {} {} {} {} H :0 {}', client.nick, channelname,
                     self.user, self.host, client.server.name,
                     self.nick, self.realname)

    def on_whois(self, client):
        client.reply('311 {} {} {} {} * :{}', client.nick, self.nick,
                     self.user, self.host, self.realname)
        client.reply('319 {} {} :{}', client.nick, self.nick,
                     ' '.join(name for name in
                              client.channels.keys() & self.channels.keys()))

    def on_websocket(self, data):
        command = data['command']
        if type(SpecialCommands.__dict__.get(command)) == staticmethod:
            getattr(SpecialCommands, command)(self, data)

    def on_websocket_open(self, peername):
        status = StatusChannel.instance
        #self.status('WebSocket client connected from {}'.format(peername))

    def on_websocket_close(self, peername):
        # PART all special channels, these chatrooms will be garbage collected
        for room in self.name2special_room.values():
            if room.joined:
                room.on_part(self, 'WebSocket client disconnection')
        self.name2special_room.clear()
        self.username2special_room.clear()

        # instead of flooding +wechat with massive PART messages,
        # take the shortcut by rejoining the client
        self.nick2special_user.clear()
        self.username2special_user.clear()
        status = StatusChannel.instance
        status.shadow_members.get(self, set()).clear()
        if self in status.members:
            status.on_part(self, 'WebSocket client disconnected from {}'.format(peername))
            status.on_join(self)

    def on_websocket_message(self, data):
        msg = data['message']
        sender = self.ensure_special_user(data['sender'])
        for line in msg.splitlines():
            self.server.irc_log(sender, datetime.fromtimestamp(data['time']), sender, line)
            if 'server-time' in self.capabilities:
                self.write('@time={}Z :{} PRIVMSG {} :{}'.format(
                    datetime.fromtimestamp(data['time'], timezone.utc).strftime('%FT%T.%f')[:23],
                    sender.prefix, self.nick, line))
            else:
                self.write(':{} PRIVMSG {} :{}'.format(
                    sender.prefix, self.nick, line))


class SpecialUser:
    def __init__(self, client, record, friend):
        self.client = client
        self.username = record['UserName']
        self.channels = set()
        self.is_friend = False
        self.record = {}
        self.uin = 0
        self.update(client, record, friend)
        self.log_file = None

    @property
    def prefix(self):
        return '{}!{}@{}'.format(self.nick, self.username.replace('@', ''), im_name)

    def name(self):
        # items in MemberList do not have 'DisplayName' or 'RemarkName'
        if self.username.startswith('@'):
            base = re.sub('^[&#!+]*', '', irc_escape(self.record.get('DisplayName', '')))
        # special contacts, e.g. filehelper
        else:
            base = irc_escape(self.username)
        return base or 'Guest'

    def update(self, client, record, friend):
        if not self.record or 'RemarkName' in record:
            self.record.update(record)
            uin = self.record.get('Uin', 0)
            if uin > 0:
                self.uin = uin
        old_nick = getattr(self, 'nick', None)
        base = self.name()
        suffix = ''
        while 1:
            nick = base+suffix
            if nick and (nick == old_nick or
                         irc_lower(nick) != irc_lower(client.nick) and
                         not client.has_special_user(nick)):
                break
            suffix = str(int(suffix or 0)+1)
        if nick != old_nick:
            for channel in self.channels:
                channel.nick_event(self, nick)
            self.nick = nick
        # friend
        if friend > 0:
            if not self.is_friend:
                self.is_friend = True
                StatusChannel.instance.on_join(self)
                for channel in self.channels:
                    if isinstance(channel, SpecialChannel):
                        channel.members[self] = 'v'
                        channel.voice_event(self)
        # non_friend
        elif friend < 0:
            if self.is_friend:
                self.is_friend = False
                StatusChannel.instance.on_part(self)
                for channel in self.channels:
                    if isinstance(channel, SpecialChannel):
                        channel.members[self] = ''
                        channel.devoice_event(self)
        # unsure

    def enter(self, channel):
        self.channels.add(channel)

    def leave(self, channel):
        self.channels.remove(channel)

    def on_notice_or_privmsg(self, client, command, msg):
        if not client.ctcp(self.username, command, msg):
            client.server.irc_log(self, datetime.now(), client, msg)
            Web.instance.send_text_message(self.username, msg)

    def on_who_member(self, client, channelname):
        client.reply('352 {} {} {} {} {} {} H :0 {}', client.nick, channelname,
                     self.username, im_name, client.server.name,
                     self.nick, self.username)

    def on_whois(self, client):
        client.reply('311 {} {} {} {} * :{}', client.nick, self.nick,
                     self.username, im_name, self.record.get('NickName', ''))

    def on_websocket_message(self, data):
        msg = data['message']
        for line in msg.splitlines():
            self.client.server.irc_log(self, datetime.fromtimestamp(data['time']), self.client, line)
            if 'server-time' in self.client.capabilities:
                self.client.write('@time={}Z :{} PRIVMSG {} :{}'.format(
                    datetime.fromtimestamp(data['time'], timezone.utc).strftime('%FT%T.%f')[:23],
                    self.client.prefix, self.nick, line))
            else:
                self.client.write(':{} PRIVMSG {} :{}'.format(
                    self.client.prefix, self.nick, line))


class Server:
    valid_nickname = re.compile(r"^[][\`_^{|}A-Za-z][][\`_^{|}A-Za-z0-9-]{0,50}$")
    # initial character `+` is reserved for special channels
    # initial character `&` is reserved for special chatrooms
    valid_channelname = re.compile(r"^[#!][^\x00\x07\x0a\x0d ,:]{0,50}$")
    instance = None

    def __init__(self, options):
        self.options = options
        status = StatusChannel(self)
        self.channels = {status.name: status}
        self.name = 'wechatircd.maskray.me'
        self.nicks = {}
        self.clients = weakref.WeakSet()

        self._boot = datetime.now()

        assert not Server.instance
        Server.instance = self

    def _accept(self, reader, writer):
        def done(task):
            if client.nick:
                self.remove_nick(client.nick)

        try:
            client = Client(self, reader, writer, self.options)
            self.clients.add(client)
            task = self.loop.create_task(client.handle_irc())
            task.add_done_callback(done)
        except Exception as e:
            traceback.print_exc()

    def has_channel(self, channelname):
        return irc_lower(channelname) in self.channels

    def get_channel(self, channelname):
        return self.channels[irc_lower(channelname)]

    # IRC channel or special chatroom
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
        if lower in self.nicks or lower in client.nick2special_user:
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

    def start(self, loop, tls):
        self.loop = loop
        self.servers = []
        for i in self.options.irc_listen if self.options.irc_listen else self.options.listen:
            self.servers.append(loop.run_until_complete(
                asyncio.streams.start_server(self._accept, i, self.options.irc_port, ssl=tls)))

    def stop(self):
        for i in self.servers:
            i.close()
            self.loop.run_until_complete(i.wait_closed())

    ## WebSocket
    def on_websocket(self, data):
        for client in self.clients:
            client.on_websocket(data)

    def irc_log(self, channel, local_time, sender, line):
        if self.options.logger_mask is None:
            return
        for regex in self.options.logger_ignore or []:
            if re.search(regex, channel.name):
                return
        filename = local_time.strftime(self.options.logger_mask.replace('$channel', channel.nick))
        time_str = local_time.strftime(self.options.logger_time_format.replace('$channel', channel.nick))
        if channel.log_file is None or channel.log_file.name != filename:
            if channel.log_file is not None:
                channel.log_file.close()
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            channel.log_file = open(filename, 'a')
        channel.log_file.write('{}\t{}\t{}\n'.format(time_str, sender.nick, line))
        channel.log_file.flush()


def main():
    ap = ArgumentParser(description='wechatircd brings wx.qq.com to IRC clients')
    ap.add_argument('-d', '--debug', action='store_true', help='run ipdb on uncaught exception')
    ap.add_argument('--dcc-send', type=int, default=10*1024*1024, help='size limit receiving from DCC SEND. 0: disable DCC SEND')
    ap.add_argument('--heartbeat', type=int, default=30, help='time to wait for IRC commands. The server will send PING and close the connection after another timeout of equal duration if no commands is received.')
    ap.add_argument('--http-cert', help='TLS certificate for HTTPS/WebSocket over TLS. You may concatenate certificate+key, specify a single PEM file and omit `--http-key`. Use HTTP if neither --http-cert nor --http-key is specified')
    ap.add_argument('--http-key', help='TLS key for HTTPS/WebSocket over TLS')
    ap.add_argument('--http-listen', nargs='*',
                    help='HTTP/WebSocket listen addresses (overriding --listen)')
    ap.add_argument('--http-port', type=int, default=9000, help='HTTP/WebSocket listen port, default: 9000')
    ap.add_argument('--http-root', default=os.path.dirname(__file__), help='HTTP root directory (serving injector.js)')
    ap.add_argument('-i', '--ignore', nargs='*',
                    help='list of ignored regex, do not auto join to a '+im_name+' chatroom whose channel name(generated from DisplayName) matches')
    ap.add_argument('-I', '--ignore-display-name', nargs='*',
                    help='list of ignored regex, do not auto join to a '+im_name+' chatroom whose DisplayName matches')
    ap.add_argument('--irc-cert', help='TLS certificate for IRC over TLS. You may concatenate certificate+key, specify a single PEM file and omit `--irc-key`. Use plain IRC if neither --irc-cert nor --irc-key is specified')
    ap.add_argument('--irc-key', help='TLS key for IRC over TLS')
    ap.add_argument('--irc-listen', nargs='*',
                    help='IRC listen addresses (overriding --listen)')
    ap.add_argument('--irc-password', default='', help='Set the IRC connection password')
    ap.add_argument('--irc-port', type=int, default=6667,
                    help='IRC server listen port. defalt: 6667')
    ap.add_argument('-j', '--join', choices=['all', 'auto', 'manual'], default='auto',
                    help='join mode for '+im_name+' chatrooms. all: join all after connected; auto: join after the first message arrives; manual: no automatic join. default: auto')
    ap.add_argument('-l', '--listen', nargs='*', default=['127.0.0.1'],
                    help='IRC/HTTP/WebSocket listen addresses, default: 127.0.0.1')
    ap.add_argument('--logger-ignore', nargs='*', help='list of ignored regex, do not log contacts/chatrooms whose names match')
    ap.add_argument('--logger-mask', help='WeeChat logger.mask.irc')
    ap.add_argument('--logger-time-format', default='%H:%M', help='WeeChat logger.file.time_format')
    ap.add_argument('--password', help='admin password')
    ap.add_argument('-q', '--quiet', action='store_const', const=logging.WARN, dest='loglevel')
    ap.add_argument('-v', '--verbose', action='store_const', const=logging.DEBUG, dest='loglevel')
    options = ap.parse_args()

    if sys.platform == 'linux':
        # send to syslog if run as a daemon (no controlling terminal)
        try:
            with open('/dev/tty'):
                pass
            logging.basicConfig(format='%(levelname)s: %(message)s')
        except OSError:
            logging.root.addHandler(logging.handlers.SysLogHandler('/dev/log'))
    else:
        logging.basicConfig(format='%(levelname)s: %(message)s')
    logging.root.setLevel(options.loglevel or logging.INFO)

    if options.http_cert or options.http_key:
        http_tls = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
        http_tls.load_cert_chain(options.http_cert or options.http_key,
                                 options.http_key or options.http_cert)
    else:
        http_tls = None
    if options.irc_cert or options.irc_key:
        irc_tls = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
        irc_tls.load_cert_chain(options.irc_cert or options.irc_key,
                                 options.irc_key or options.irc_cert)
    else:
        irc_tls = None

    loop = asyncio.get_event_loop()
    if options.debug:
        sys.excepthook = ExceptionHook()
    server = Server(options)
    web = Web(options.http_root)

    server.start(loop, irc_tls)
    web.start(options.http_listen if options.http_listen else options.listen,
              options.http_port, http_tls, loop)
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        server.stop()
        web.stop()
        loop.stop()


if __name__ == '__main__':
    sys.exit(main())
