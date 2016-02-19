#!/usr/bin/env python3
from argparse import ArgumentParser
from autobahn.asyncio.websocket import \
    WebSocketServerProtocol, WebSocketServerFactory
from enum import Enum
from ipdb import set_trace as bp
import asyncio, inspect, json, logging, pprint, re, signal, string, sys, traceback, uuid, weakref

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

### WebSocket

class WSProtocol(WebSocketServerProtocol):
    instance = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.token2transport = {}
        self.transport2token = {}
        if not WSProtocol.instance:
            WSProtocol.instance = self

    def onMessage(self, payload, isBinary):
        try:
            data = json.loads(payload.decode())
            token = data['token']
            t = self.transport
            assert isinstance(token, str) and re.match(r'^[0-9a-f]{32}$', token)
            if t in self.transport2token and self.transport2token[t] != token:
                self.token2transport.pop(self.transport2token[t])
                self.transport2token.pop(t)
            elif t not in self.transport2token:
                self.transport2token[t] = token
                self.token2transport[token] = t
            Server.instance.on_wechat_message(data)
        except:
            raise
            pass

    def onClose(self, was_clean, code, reason):
        t = self.transport
        if t in self.transport2token:
            self.token2transport.pop(self.transport2token[t])
            self.transport2token.pop(t)

    def send(self, token, receiver, msg):
        if token in self.token2transport:
            old = self.transport
            try:
                self.transport = self.token2transport[token]
                self.sendMessage(json.dumps({
                    'command': 'send_text_message',
                    'receiver': receiver,
                    'message': msg,
                    #@ webwxapp.js /e.ClientMsgId = e.LocalID = e.MsgId = (utilFactory.now() + Math.random().toFixed(3)).replace(".", ""),
                    'local_id': int(time.time()*1000)+'0'+str(random.randint(0, 999)),
                }, ensure_ascii=False).encode())
            except:
                traceback.print_exc()
                pass
            finally:
                self.transport = old

### IRC

def irc_lower(s):
    irc_trans = str.maketrans(string.ascii_uppercase+'[]\\^',
                              string.ascii_lowercase+'{}|~')
    return s.translate(irc_trans)


# loose
def irc_escape(s):
    return re.sub(r'[^-\w,\.@%\(\)=]', '', s)


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
                        channel = client.server.get_channel(channelname)
                        if channel.on_join(client):
                            client.channels[irc_lower(channelname)] = channel
                    except ValueError:
                        client.err_nosuchchannel(channelname)

    @staticmethod
    def lusers(client):
        client.reply('251 :There are {} users', len(client.server.nicks))

    @staticmethod
    def nick(client, *args):
        if not args:
            client.err_nonicknamegiven()
            return
        client.server.change_nick(client, args[0])

    @staticmethod
    def part(client, arg, *args):
        if args:
            msg = args[0]
        else:
            msg = None
        for channelname in arg.split(','):
            client.part(channelname, msg)

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
        if not args:
            client.err_norecipient('PRIVMSG')
            return
        if len(args) == 1:
            client.err_notexttosend()
            return
        target = args[0]
        msg = args[1]
        # on name conflicts, prefer to resolve WeChat friend first
        if client.has_wechat_friend(target):
            friend = client.get_wechat_friend(target)
            WSProtocol.instance.send(client.token, friend['UserName'], msg)
        # then IRC nick
        elif client.server.has_nick(target):
            client2 = client.server.get_nick(target)
            client2.write(':{} {} {} :{}'.format(client.prefix, 'PRIVMSG', target, msg))
        # IRC channel or WeChat chatroom
        elif client.is_in_channel(target):
            channel = client.get_channel(target).on_privmsg(client, msg)
        else:
            client.err_nosuchnick(target)

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


class Channel:
    def __init__(self, server, name):
        self.server = server
        self.name = name
        self.topic = ''
        self.members = set()

    def on_privmsg(self, client, msg):
        if client not in self.members:
            client.err_notonchannel(self.name)
            return
        line = ':{} PRIVMSG {} :{}'.format(client.prefix, self.name, msg)
        for client2 in self.members:
            if client2 != client:
                client2.write(line)

    def on_event(self, client, command, *args):
        if len(args) == 1:
            msg = args[0]
        elif len(args) == 2:
            msg = '{} :{}'.format(*args)
        line = ':{} {} {}'.format(client.prefix, command, msg)
        for client in self.members:
            client.write(line)

    def on_join(self, client):
        if client in self.members:
            return False
        self.members.add(client)
        self.on_event(client, 'JOIN', self.name)
        client.reply('353 = {} :{}', self.name, ' '.join(sorted(x.nick for x in self.members)))
        client.reply('366 {} :End of NAMES list', self.name)
        info('%s joined %s', client.prefix, self.name)
        return True

    def on_part(self, client, msg):
        if client not in self.members:
            client.err_notonchannel(self.name)
            return False
        if msg:
            self.on_event(client, 'PART', msg)
        self.members.remove(client)
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
        if not StatusChannel.instance:
            StatusChannel.instance = self
        self.shadow_members = weakref.WeakKeyDictionary()

    def add_member(self, client, member):
        ref = weakref.ref(client)
        if ref not in self.shadow_members:
            self.shadow_members[ref] = set()
        self.shadow_members[ref].add(member)
        self.on_event(client, 'JOIN', self.name)

    def respond(self, client, msg, *args):
        if args:
            client.write((':{} PRIVMSG {} :'+msg).format(self.name, self.name, *args))
        else:
            client.write((':{} PRIVMSG {} :').format(self.name, self.name)+msg)

    def on_privmsg(self, client, msg):
        if client not in self.members:
            client.err_notonchannel(self.name)
            return
        if msg == 'help':
            self.respond(client, 'new [token]  generate new token or use specified token')
            self.respond(client, 'help         display this help')
        elif msg == 'new':
            client.new_token()
            self.respond(client, 'new token {}', client.token)
        elif msg == 'status':
            self.respond(client, 'Token: {}', client.token)
            self.respond(client, 'Channels: {}', ','.join(client.channels.keys()))
            self.respond(client, 'WeChat friends:')
            for name, record in client.name2wechat_friend.items():
                self.respond(client, name+': '+pprint.pformat(record))
            self.respond(client, 'WeChat rooms:')
            for name, room in client.channels.items():
                if isinstance(room, WeChatRoom):
                    self.respond(client, name+': '+pprint.pformat(room.record))
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

    def on_event(self, client, command, *args):
        if len(args) == 1:
            msg = args[0]
        elif len(args) == 2:
            msg = '{} :{}'.format(*args)
        line = ':{} {} {}'.format(client.prefix, command, msg)
        client.write(line)


class WeChatRoom:
    def __init__(self, client, record):
        base = '#'+irc_escape(record['RemarkName'] or record['NickName'])
        suffix = ''
        while 1:
            if not client.is_in_channel(base+suffix):
                break
            suffix = str(int(suffix or 0)+1)
        self.name = record['Name'] = base+suffix
        self.username = record['UserName']
        self.record = record
        self.joined = False
        self.members = {}

    def add_member(self, record):
        self.members[record['UserName']] = record

    def on_privmsg(self, client, msg):
        WSProtocol.instance.send(client.token, self.username, msg)

    def on_event(self, client, command, *args):
        if len(args) == 1:
            msg = args[0]
        elif len(args) == 2:
            msg = '{} :{}'.format(*args)
        line = ':{} {} {}'.format(client.prefix, command, msg)
        client.write(line)
        if command == 'JOIN':
            # TODO
            pass

    def on_join(self, client):
        if self.joined:
            return False
        self.joined = True
        self.on_event(client, 'JOIN', self.name)
        client.reply('353 = {} :{}', self.name, ' '.join(sorted(x['NickName'] for x in self.members)))
        client.reply('366 {} :End of NAMES list', self.name)
        info('%s joined %s', client.prefix, self.name)
        return True

    def on_part(self, client, msg):
        '''Leaving a WeChat chatroom is disallowed'''
        client.err_unknowncommand('PART')


class Client:
    def __init__(self, server, reader, writer):
        self.server = server
        self.reader = reader
        self.writer = writer
        peer = writer.get_extra_info('socket').getpeername()
        self.host = peer[0]
        self.nick = None
        self.user = None
        self.registered = False
        self.channels = {}
        self.name2wechat_friend = {} # 表示名到微信朋友
        self.wechat_friend2name = {} # 微信朋友UserName到表示名的映射
        self.username2wechat_room = {} # 微信群UserName到WeChatRoom的映射
        self.token = None
        self.new_token()

    def change_token(self, new):
        return self.server.change_token(self, new)

    def new_token(self):
        return self.change_token(uuid.uuid1().hex)

    def ensure_wechat_friend(self, friend):
        assert isinstance(friend['UserName'], str)
        assert isinstance(friend['RemarkName'], str)
        assert isinstance(friend['NickName'], str)
        if friend['UserName'] in self.wechat_friend2name:
            friend.update(self.name2wechat_friend[self.wechat_friend2name[friend['UserName']]])
            return
        if friend['UserName'].startswith('@'):
            base = irc_escape(friend['RemarkName'] or friend['NickName'])
        else:
            base = irc_escape(friend['UserName'])
        suffix = ''
        while 1:
            lower = irc_lower(base+suffix)
            if lower != irc_lower(self.nick) and not self.has_wechat_friend(lower):
                break
            suffix = str(int(suffix or 0)+1)
        friend['Name'] = base+suffix
        self.name2wechat_friend[irc_lower(friend['Name'])] = friend
        self.wechat_friend2name[friend['UserName']] = irc_lower(friend['Name'])
        StatusChannel.instance.add_member(self, friend)

    def ensure_wechat_room(self, record):
        assert isinstance(record['UserName'], str)
        assert isinstance(record['RemarkName'], str)
        assert isinstance(record['NickName'], str)
        if record['UserName'] in self.username2wechat_room:
            room = self.username2wechat_room[record['UserName']]
            record.update(room.record)
        else:
            room = WeChatRoom(self, record)
            room.on_join(self)
            self.channels[irc_lower(room.name)] = room
            self.username2wechat_room[room.username] = room
        return room

    def has_wechat_friend(self, name):
        return irc_lower(name) in self.name2wechat_friend

    def get_wechat_friend(self, name):
        return self.name2wechat_friend[irc_lower(name)]

    def is_in_channel(self, name):
        return irc_lower(name) in self.channels

    def get_channel(self, channelname):
        return self.channels[irc_lower(channelname)]

    def disconnect(self, quitmsg):
        self.write('ERROR :{}'.format(quitmsg))
        info('Disconnection from %s', self.nick)
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
        self.get_channel(channelname).on_part(self, msg if msg else channelname)

    def message_related(self, include_self, msg):
        clients = set()
        for channel in self.channels.values():
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
        if hasattr(cls, cmd):
            if type(cls.__dict__[cmd]) == staticmethod:
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
                        status_channel.on_privmsg(self, 'new')
                ret = True
        if not ret:
            self.err_unknowncommand(command)

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


class WeChatUser:
    def __init__(self, client, record):
        pass


class Server:
    valid_nickname = re.compile(r"^[][\`_^{|}A-Za-z][][\`_^{|}A-Za-z0-9-]{0,50}$")
    # + is reserved for special channels
    valid_channelname = re.compile(r"^[&#!][^\x00\x07\x0a\x0d ,:]{0,50}$")
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
            #await task
        except Exception as e:
            traceback.print_exc()

    # IRC channel or WeChat chatroom
    def has_channel(self, channelname):
        return irc_lower(channelname) in self.channels

    # IRC channel or WeChat chatroom
    def get_channel(self, channelname):
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
        if irc_lower(new) in self.nicks:
            client.err_nicknameinuse(new)
        elif not Server.valid_nickname.match(new):
            client.err_errorneusnickname(new)
        else:
            info('%s changed nick to %s', client.prefix, new)
            if client.nick:
                self.nicks.pop(irc_lower(client.nick))
            self.nicks[irc_lower(new)] = client
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
    def on_wechat_message(self, data):
        def handle_friend(data):
            client.ensure_wechat_friend(data['record'])

        def handle_room(data):
            room = client.ensure_wechat_room(data['record'])
            for member in record['MemberList']:
                room.add_member(member)

        def handle_message(data):
            msg = data['message']
            # 微信群
            if data.get('room', None):
                room = data['room']
                client.ensure_wechat_room(room)
                room_name = '#' + (room['RemarkName'] or room['NickName'])
                if data['type'] == 'send':
                    #client.write(':{} PRIVMSG {} :{}'.format(
                    #    client.prefix, room['Name'], msg))
                    pass
                else:
                    peer = data['sender']
                    client.ensure_wechat_friend(peer)
                    client.write(':{} PRIVMSG {} :{}'.format(
                        peer['Name'], room['Name'], msg))
            # 微信朋友
            else:
                if data['type'] == 'send':
                    peer = data['receiver']
                else:
                    peer = data['sender']
                client.ensure_wechat_friend(peer)
                if data['type'] == 'send':
                    #receiver = data['receiver']
                    #client.write(':{} PRIVMSG {} :{}'.format(
                    #    client.prefix, peer['Name'], msg))
                    pass
                else:
                    client.write(':{} PRIVMSG {} :{}'.format(
                        peer['Name'], client.nick, msg))

        token = data['token']
        if token in self.tokens:
            handlers = {'friend': handle_friend,
                        'room': handle_room,
                        'send': handle_message,
                        'receive': handle_message,
                        }
            client = self.tokens[token]
            debug(data)
            if data['type'] in handlers:
                handlers[data['type']](data)


def main():
    ap = ArgumentParser()
    ap.add_argument('-q', '--quiet', action='store_const', const=logging.WARN, dest='loglevel')
    ap.add_argument('-v', '--verbose', action='store_const', const=logging.DEBUG, dest='loglevel')
    ap.add_argument('-t', '--tags', action='store_true', help='generate tags for wx.js')
    ap.add_argument('-d', '--debug', action='store_true', help='run ipdb on uncaught exception')
    ap.add_argument('-l', '--listen', default='127.0.0.1', help='listen address')
    ap.add_argument('-p', '--port', type=int, default=6667, help='listen port')
    ap.add_argument('--password', help='admin password')
    ap.add_argument('--ws-port', type=int, default=9000, help='WebSocket listen port')
    ap.add_argument('--heartbeat', type=int, default=1000, help='heartbeat') # TODO
    options = ap.parse_args()
    logging.basicConfig(level=options.loglevel or logging.INFO,
                        format='%(asctime)s:%(levelname)s: %(message)s')

    loop = asyncio.get_event_loop()
    if options.debug:
        sys.excepthook = ExceptionHook()
    server = Server(options)

    factory = WebSocketServerFactory('ws://{}:{}'.format(options.listen, options.ws_port))
    factory.protocol = WSProtocol
    loop.run_until_complete(loop.create_server(factory, options.listen, options.ws_port))
    server.start(loop)
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        server.stop()


if __name__ == '__main__':
    sys.exit(main())
