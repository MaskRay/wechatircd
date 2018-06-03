#!/usr/bin/env python3
from configargparse import ArgParser, Namespace
#from ipdb import set_trace as bp
from collections import deque
from datetime import datetime, timezone
from itertools import chain
import aiohttp.web, async_timeout, asyncio, base64, inspect, json, logging.handlers, os, pprint, random, re, \
    signal, socket, ssl, string, sys, time, traceback, uuid, weakref

logger = logging.getLogger('wechatircd')
im_name = 'WeChat'
capabilities = set(['draft/message-tags', 'echo-message', 'multi-prefix', 'sasl', 'server-time'])  # http://ircv3.net/irc/
options = None
server = None
web = None


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
    def __init__(self, tls):
        global web
        web = self
        self.tls = tls
        self.id2media = {}
        self.id2message = {}
        self.recent_messages = deque()
        self.ws = weakref.WeakSet()

    async def handle_index(self, request):
        with open(os.path.join(options.http_root, 'index.html'), 'rb') as f:
            return aiohttp.web.Response(body=f.read())

    async def handle_index_js(self, request):
        try:
            with open(os.path.join(options.http_root, 'index.js'), 'rb') as f:
                return aiohttp.web.Response(body=f.read(),
                    headers={'Content-Type': 'application/javascript; charset=UTF-8',
                             'Access-Control-Allow-Origin': '*'})
        except FileNotFoundError:
            return aiohttp.web.Response(status=404, text='Not Found')

    async def handle_injector_js(self, request):
        try:
            with open(os.path.join(options.http_root, 'injector.js'), 'rb') as f:
                return aiohttp.web.Response(
                    body=f.read().replace(b'@WEBSOCKET_URL', 'wss://{}/ws'.format(request.headers['Host']).encode()),
                    headers={'Content-Type': 'application/javascript; charset=UTF-8',
                             'Access-Control-Allow-Origin': '*'})
        except FileNotFoundError:
            return aiohttp.web.Response(status=404, text='Not Found. Wrong --http-root ?')
        except KeyError:
            return aiohttp.web.Response(status=400, text='Missing Host:')

    async def handle_media(self, request):
        id = re.sub(r'\..*', '', request.match_info.get('id'))
        if id not in self.id2media:
            return aiohttp.web.Response(status=404, text='Not Found')
        try:
            media = self.id2media[id]
            with async_timeout.timeout(30, loop=server.loop):
                async with aiohttp.ClientSession() as session:
                    async with session.get(media['url'], headers={'Cookie': media['cookie']}) as resp:
                        response = await aiohttp.web.StreamResponse(status=resp.status, reason=resp.reason, headers={'Content-Type': resp.headers.get('content-type', 'application/octet-stream')})
                        await response.prepare(request)
                        while True:
                            chunk = await resp.content.readany()
                            if not chunk:
                                await response.write_eof()
                                break
                            response.write(chunk)
                            await response.drain()
                        return response
        except asyncio.TimeoutError:
            return aiohttp.web.Response(status=504, text='I used to live in 504A')
        except Exception as ex:
            return aiohttp.web.Response(status=500, text=str(ex))

    async def handle_web_socket(self, request):
        ws = aiohttp.web.WebSocketResponse(heartbeat=options.heartbeat)
        self.ws.add(ws)
        peername = request.transport.get_extra_info('peername')
        info('WebSocket client connected from %r', peername)
        await ws.prepare(request)
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    server.on_websocket(data)
                except AssertionError:
                    info('WebSocket client error')
                    break
                except:
                    raise
            elif msg.type == aiohttp.WSMsgType.CLOSE:
                info('WebSocket client close')
                break
        info('WebSocket client disconnected from %r', peername)
        server.on_websocket_close(peername)
        self.ws.remove(ws)
        return ws

    def start(self, listens, port, loop):
        self.loop = loop
        self.app = aiohttp.web.Application()
        self.app.router.add_route('GET', '/', self.handle_index)
        self.app.router.add_route('GET', '/index.js', self.handle_index_js)
        self.app.router.add_route('GET', '/injector.js', self.handle_injector_js)
        self.app.router.add_route('GET', '/media/{id}', self.handle_media)
        self.app.router.add_route('GET', '/ws', self.handle_web_socket)
        self.handler = self.app.make_handler()
        self.srv = []
        for i in listens:
            self.srv.append(loop.run_until_complete(
                loop.create_server(self.handler, i, port, ssl=self.tls)))

    def stop(self):
        for i in self.srv:
            i.close()
            self.loop.run_until_complete(i.wait_closed())
        self.loop.run_until_complete(self.app.shutdown())
        self.loop.run_until_complete(self.handler.finish_connections(0))
        self.loop.run_until_complete(self.app.cleanup())

    def append_history(self, data):
        if len(self.recent_messages) >= 10000:
            msg = self.recent_messages.popleft()
            del self.id2message[msg['id']]
        self.recent_messages.append(data)
        self.id2message[data['id']] = data

    def send_command(self, data):
        for ws in web.ws:
            try:
                self.loop.create_task(ws.send_str(json.dumps(data)))
            except:
                pass
            break

    def logout(self):
        self.send_command({'command': 'logout'})

    def reload(self):
        self.send_command({'command': 'reload'})

    def send_file(self, receiver, filename, body):
        self.send_command({
            'command': 'send_file',
            'receiver': receiver,
            'filename': filename,
            'body': body.decode('latin-1'),
        })

    def send_text_message(self, client, receiver, msg):
        self.send_command({
            'command': 'send_text_message',
            'client': client.nick,
            'receiver': receiver,
            'text': msg,
        })

    def add_friend(self, username, message):
        self.send_command({
            'command': 'add_friend',
            'user': username,
            'text': message,
        })

    def add_member(self, roomname, username):
        self.send_command({
            'command': 'add_member',
            'room': roomname,
            'user': username,
        })

    def del_member(self, roomname, username):
        self.send_command({
            'command': 'del_member',
            'room': roomname,
            'user': username,
        })

    def mod_topic(self, roomname, topic):
        self.send_command({
            'command': 'mod_topic',
            'room': roomname,
            'topic': topic,
        })

    def reload_contact(self, who):
        self.send_command({
            'command': 'reload_contact',
            'name': who,
        })

    def web_eval(self, expr):
        self.send_command({
            'command': 'eval',
            'expr': expr,
        })

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


def irc_escape_nick(s):
    return re.sub('^[&#!+:]*', '', irc_escape(s))


def process_text(to, text):
    # !m
    # @(\d\d)(\d\d)(\d\d)?
    reply = None
    multiline = False
    while 1:
        cont = False
        match = re.match(r'@(\d\d)(\d\d)(\d\d)? ', text)
        if match:
            cont = True
            text = text[match.end():]
            HH, MM, SS = int(match.group(1)), int(match.group(2)), match.group(3)
            if SS is not None:
                SS = int(SS)
            for msg in reversed(web.recent_messages):
                if msg['to'] == to.username:
                    dt = datetime.fromtimestamp(msg['time'])
                    if dt.hour == HH and dt.minute == MM and (SS is None or dt.second == SS):
                        reply = msg
                        break
        match = re.match(r'@(\d{1,2}) ', text)
        if match:
            cont = True
            text = text[match.end():]
            which = int(match.group(1))
            in_channel = isinstance(to, SpecialChannel)
            if which > 0:
                for msg in reversed(web.recent_messages):
                    if in_channel and msg['to'] == to.username and msg['from'] != server or \
                            not in_channel and msg['from'] == to and msg['to'] == server.username:
                        which -= len(msg['text'].splitlines())
                        if which <= 0:
                            reply = msg
                            break
        if text.startswith('!m '):
            cont = True
            text = text[3:]
            multiline = True
        if not cont: break
    if multiline:
        text = text.replace('\\n', '\n')

    # nick: -> @Group Alias or SpecialUser#name
    at = ''
    i = 0
    while i < len(text) and text[i] != ' ':
        j = text.find(': ', i)
        if j == -1: break
        nick = text[i:j]
        if not server.has_special_user(nick): break
        user = server.get_special_user(nick)
        if to in user.channel2nick:
            at += '@{} '.format(user.channel2nick[to] or server.get_special_user(nick).alias())
        else:
            at += '@{} '.format(server.get_special_user(nick).alias())
        i = j+2
    text = at+text[i:]

    if reply:
        refer_text = reply['text'].replace('\n', '\\n')
        if len(refer_text) > 8:
            refer_text = refer_text[:8]+'...'
        refer_from = reply['from']
        if refer_from == server:
            text = '「Re: {}」{}'.format(refer_text, text)
        else:
            if to in refer_from.channel2nick:
                refer_from = refer_from.channel2nick[to] or refer_from.alias()
            else:
                refer_from = refer_from.alias()
            text = '「Re {}: {}」{}'.format(refer_from, refer_text, text)
    return text


def irc_log(where, peer, local_time, sender, line):
    if options.logger_mask is None:
        return
    for regex in options.logger_ignore or []:
        if re.search(regex, peer.name):
            return
    filename = local_time.strftime(options.logger_mask.replace('$channel', peer.nick))
    time_str = local_time.strftime(options.logger_time_format.replace('$channel', peer.nick))
    if where.log_file is None or where.log_file.name != filename:
        if where.log_file is not None:
            where.log_file.close()
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        where.log_file = open(filename, 'a')
    where.log_file.write('{}\t{}\t{}\n'.format(
        time_str, sender.nick,
        re.sub(r'\x03\d+(,\d+)?|[\x02\x0f\x1d\x1f\x16]', '', line)))
    where.log_file.flush()


def irc_privmsg(client, command, to, text):
    if command == 'PRIVMSG' and client.ctcp(to, text):
        return

    def send():
        web.send_text_message(client, to.username, to.privmsg_text)
        to.privmsg_text = ''

    async def wait(seq):
        await asyncio.sleep(options.paste_wait)
        if to.privmsg_seq == seq:
            send()

    text = process_text(to, text)
    to.privmsg_seq = to.privmsg_seq+1
    if len(to.privmsg_text):
        to.privmsg_text += '\n'
    to.privmsg_text += text
    server.loop.create_task(wait(to.privmsg_seq))

### Commands

cmd_use_case = {}


def registered(v):
    def wrapped(fn):
        cmd_use_case[fn.__name__] = v
        return fn
    return wrapped


class Command:
    @staticmethod
    @registered(3)
    def authenticate(client, arg):
        if arg.upper() == 'PLAIN':
            client.write('AUTHENTICATE +')
            return
        if not (client.nick and client.user):
            return
        try:
            if base64.b64decode(arg).split(b'\0')[2].decode() == options.sasl_password:
                client.authenticated = True
                client.reply('900 {} {} {} :You are now logged in as {}', client.nick, client.user, client.nick, client.nick)
                client.reply('903 {} :SASL authentication successful', client.nick)
                client.register()
            else:
                client.reply('904 {} :SASL authentication failed', client.nick)
        except Exception as ex:
            client.reply('904 {} :SASL authentication failed', client.nick)

    @staticmethod
    def away(client):
        pass

    @staticmethod
    @registered(3)
    def cap(client, *args):
        if not args: return
        comm = args[0].lower()
        if comm == 'list':
            client.reply('CAP * LIST :{}', ' '.join(client.capabilities))
        elif comm == 'ls':
            client.reply('CAP * LS :{}', ' '.join(capabilities))
        elif comm == 'req':
            enabled, disabled = set(), set()
            for name in args[1].split():
                if name.startswith('-'):
                    disabled.add(name[1:])
                else:
                    enabled.add(name)
            client.capabilities = (capabilities & enabled) - disabled
            client.reply('CAP * ACK :{}', ' '.join(client.capabilities))

    @staticmethod
    def info(client):
        client.rpl_info('{} users', len(server.nicks))
        client.rpl_info('{} {} users', im_name, len(client.nick2special_user))
        client.rpl_info('{} {} rooms', im_name, len(client.name2special_room))

    @staticmethod
    def invite(client, nick, channelname):
        if client.is_in_channel(channelname):
            server.get_channel(channelname).on_invite(client, nick)
        else:
            client.err_notonchannel(channelname)

    @staticmethod
    def ison(client, *nicks):
        client.reply('303 {} :{}', client.nick,
                     ' '.join(nick for nick in nicks
                              if server.has_nick(nick)))

    @staticmethod
    def join(client, *args):
        if not args:
            self.err_needmoreparams('JOIN')
        else:
            arg = args[0]
            if arg == '0':
                channels = list(client.channels.values())
                for channel in channels:
                    channel.on_part(client, channel.name)
            else:
                for channelname in arg.split(','):
                    if server.has_special_room(channelname):
                        server.get_special_room(channelname).on_join(client)
                    else:
                        try:
                            server.ensure_channel(channelname).on_join(client)
                        except ValueError:
                            client.err_nosuchchannel(channelname)

    @staticmethod
    def kick(client, channelname, nick, reason=None):
        if client.is_in_channel(channelname):
            server.get_channel(channelname).on_kick(client, nick, reason)
        else:
            client.err_notonchannel(channelname)

    @staticmethod
    def kill(client, nick, reason=None):
        if not server.has_nick(nick):
            client.err_nosuchnick(nick)
            return
        user = server.get_nick(nick)
        if not isinstance(user, Client) or user == client:
            client.err_nosuchnick(nick)
            return
        user.disconnect(reason)

    @staticmethod
    def list(client, arg=None):
        if arg:
            channels = []
            for channelname in arg.split(','):
                if server.has_channel(channelname):
                    channels.append(server.get_channel(channelname))
        else:
            channels = set(server.channels.values())
            channels.update(server.name2special_room.values())
            channels = list(channels)
        channels.sort(key=lambda ch: ch.name)
        for channel in channels:
            client.reply('322 {} {} {} :{}', client.nick, channel.name,
                         channel.n_members(client), channel.topic)
        client.reply('323 {} :End of LIST', client.nick)

    @staticmethod
    def lusers(client):
        client.reply('251 :There are {} users and {} {} users on 1 server',
                     len(server.nicks),
                     len(server.nick2special_user),
                     im_name
                     )

    @staticmethod
    def mode(client, target, *args):
        if server.has_nick(target):
            if args:
                client.err_umodeunknownflag()
            else:
                client.rpl_umodeis(server.get_nick(target).mode)
        elif server.has_channel(target):
            server.get_channel(target).on_mode(client, *args)
        else:
            client.err_nosuchchannel(target)

    @staticmethod
    def motd(client):
        async def do():
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get('https://api.github.com/repos/MaskRay/wechatircd/commits') as resp:
                        client.reply('375 {} :- {} Message of the Day -', client.nick, server.name)
                        data = await resp.json()
                        for x in data[:5]:
                            client.reply('372 {} :- {} {} {}'.format(client.nick, x['sha'][:7], x['commit']['committer']['date'][:10], x['commit']['message'].replace('\n', '\\n')))
                        client.reply('376 {} :End of /MOTD command.', client.nick)
            except:
                pass
        server.loop.create_task(do())

    @staticmethod
    def names(client, target):
        if not client.is_in_channel(target):
            client.err_notonchannel(target)
            return
        server.get_channel(target).on_names(client)

    @staticmethod
    @registered(3)
    def nick(client, *args):
        if len(options.irc_password) and not client.authenticated:
            client.err_passwdmismatch('NICK')
            return
        if not args:
            client.err_nonicknamegiven()
            return
        server.change_nick(client, args[0])

    @staticmethod
    def notice(client, *args):
        Command.notice_or_privmsg(client, 'NOTICE', *args)

    @staticmethod
    def part(client, arg, *args):
        partmsg = args[0] if args else None
        for channelname in arg.split(','):
            if client.is_in_channel(channelname):
                server.get_channel(channelname).on_part(client, partmsg)
            else:
                client.err_notonchannel(channelname)

    @staticmethod
    @registered(1)
    def pass_(client, password):
        if len(options.irc_password) and password == options.irc_password:
            client.authenticated = True
            client.register()

    @staticmethod
    @registered(3)
    def ping(client, *args):
        if not args:
            client.err_noorigin()
            return
        client.reply('PONG {} :{}', server.name, args[0])

    @staticmethod
    @registered(3)
    def pong(client, *args):
        pass

    @staticmethod
    def privmsg(client, *args):
        Command.notice_or_privmsg(client, 'PRIVMSG', *args)

    @staticmethod
    def quit(client, *args):
        client.disconnect(args[0] if args else client.prefix)

    @staticmethod
    def squit(client, *args):
        web.logout()

    @staticmethod
    def stats(client, query):
        if len(query) == 1:
            if query == 'u':
                td = datetime.now() - server._boot
                client.reply('242 {} :Server Up {} days {}:{:02}:{:02}',
                             client.nick, td.days, td.seconds // 3600,
                             td.seconds // 60 % 60, td.seconds % 60)
            client.reply('219 {} {} :End of STATS report', client.nick, query)

    @staticmethod
    def summon(client, nick, msg):
        if server.has_special_user(nick):
            web.add_friend(server.get_special_user(nick).username, msg)
        else:
            client.err_nologin(nick)

    @staticmethod
    def time(client):
        client.reply('391 {} {} :{}Z', client.nick, server.name,
                     datetime.utcnow().isoformat())

    @staticmethod
    def topic(client, channelname, new=None):
        if not client.is_in_channel(channelname):
            client.err_notonchannel(channelname)
            return
        server.get_channel(channelname).on_topic(client, new)

    @staticmethod
    def who(client, target):
        if server.has_channel(target):
            server.get_channel(target).on_who(client)
        elif server.has_nick(target):
            server.get_nick(target).on_who_member(client, server)
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
        if server.has_nick(target):
            server.get_nick(target).on_whois(client)
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
        # on name conflict, prefer to resolve user first
        if server.has_nick(target):
            user = server.get_nick(target)
            if isinstance(user, Client):
                user.write(':{} PRIVMSG {} :{}'.format(client.prefix, user.nick, msg))
            elif user.is_friend:
                user.on_notice_or_privmsg(client, command, msg)
            elif command == 'PRIVMSG':
                client.err_nosuchnick(target)
        # IRC channel or special chatroom
        elif client.is_in_channel(target):
            server.get_channel(target).on_notice_or_privmsg(
                client, command, msg)
        elif command == 'PRIVMSG':
            client.err_nosuchnick(target)

    @staticmethod
    @registered(1)
    def user(client, user, mode, _, realname):
        if len(options.irc_password) and not client.authenticated:
            client.err_passwdmismatch('USER')
            return
        client.user = user
        client.realname = realname
        client.register()


class SpecialCommands:
    @staticmethod
    def add_friend_ack(data):
        nick = server.username2special_user[data['user']].nick
        for client in server.auth_clients():
            client.reply('342 {} {} :Summoning user to IRC', client.nick, nick)

    @staticmethod
    def add_friend_nak(data):
        nick = server.username2special_user[data['user']].nick
        for client in server.auth_clients():
            client.status('Friend request to {} failed'.format(nick))

    @staticmethod
    def contact(data):
        friend = data['friend']
        record = data['record']
        debug('{}: '.format('friend' if friend else 'room_contact') + ', '.join([k + ':' + repr(record.get(k)) for k in ['Alias', 'Nick', 'UserName']]))
        server.ensure_special_user(record, 1 if friend else -1)

    @staticmethod
    def delete_contact(data):
        username = data['username']
        # FIXME user
        if username in server.username2special_room:
            server.username2special_room[username].on_delete()

    @staticmethod
    def message(data):
        if data['id'] in web.id2message:
            return
        if data['from'] == 'BrandServ':
            if options.ignore_brand: return
            sender = BrandServ()
        else:
            sender = server.ensure_special_user(data['from'])
        sender_client_nick = data['client']
        if data.get('type') == 'room':
            to = server.ensure_special_room(data['to'])
        else:
            to = server.ensure_special_user(data['to'])
        data['from'] = sender
        data['to'] = to.username
        web.append_history(data)

        if data.get('media'):
            media_id = str(len(web.id2media))
            if options.http_url:
                web.id2media[media_id] = {'url': data['text'], 'cookie': data['cookie']}
                if data['media'] in ('图片', '动画表情'):
                    media_id += '.jpg'
                elif data['media'] == '语音':
                    media_id += '.mp3'
                elif data['media'] in ('视频', '小视频'):
                    media_id += '.mp4'
                text = '[{}] {}/media/{}'.format(data['media'], options.http_url, media_id)
            else:
                text = '[{}] {}'.format(data['media'], data['text'])
        else:
            text = data['text']
        for line in text.splitlines():
            if to == server or sender == server:
                client = server.preferred_client()
                if client:
                    where = sender if to == server else to
                    irc_log(where, client if where == server else where, datetime.fromtimestamp(data['time']), client if sender == server else sender, line)
            else:
                irc_log(to, to, datetime.fromtimestamp(data['time']), sender, line)
            if isinstance(to, SpecialChannel):
                for c in server.auth_clients():
                    if c not in to.joined and 'm' not in to.mode:
                        if options.join == 'auto' and c not in to.explicit_parted or options.join == 'new':
                            c.auto_join(to)
            for client in server.auth_clients():
                if (isinstance(to, Channel) and client not in to.joined) or (
                        'echo-message' not in client.capabilities and
                        client.nick == sender_client_nick):
                    continue
                sender_prefix = client.prefix if sender == server else sender.prefix
                to_nick = client.nick if to == server else to.nick
                msg = ':{} PRIVMSG {} :{}'.format(sender_prefix, to_nick, line)
                tags = []
                if 'draft/message-tags' in client.capabilities:
                    tags.append('draft/msgid={}'.format(data['id']))
                if 'server-time' in client.capabilities:
                    tags.append('time={}Z'.format(datetime.fromtimestamp(
                        data['time'], timezone.utc).strftime('%FT%T.%f')[:23]))
                if tags:
                    msg = '@{} {}'.format(';'.join(tags), msg)
                client.write(msg)

    @staticmethod
    def room(data):
        record = data['record']
        debug('room: ' + ', '.join(k + ':' + repr(record.get(k)) for k in ['Nick', 'UserName']))
        server.ensure_special_room(record).update_detail(record)

    @staticmethod
    def self(data):
        server.username = data['username']

    @staticmethod
    def send_file_message_nak(data):
        receiver = data['receiver']
        filename = data['filename']
        if server.has_special_room(receiver):
            room = server.get_special_room(receiver)
            for client in server.auth_clients():
                client.write(':{} PRIVMSG {} :[文件发送失败] {}'.format(
                    client.prefix, room.nick, filename))
        elif server.has_special_user(receiver):
            user = server.get_special_user(receiver)
            for client in server.auth_clients():
                client.write(':{} PRIVMSG {} :[文件发送失败] {}'.format(
                    client.prefix, user.nick, filename))


    @staticmethod
    def send_text_message_nak(data):
        receiver = data['receiver']
        msg = data['text']
        if server.has_special_room(receiver):
            room = server.get_special_room(receiver)
            for client in server.auth_clients():
                client.write(':{} PRIVMSG {} :[文字发送失败] {}'.format(
                    client.prefix, room.nick, msg))
        elif server.has_special_user(receiver):
            user = server.get_special_user(receiver)
            for client in server.auth_clients():
                client.write(':{} PRIVMSG {} :[文字发送失败] {}'.format(
                    client.prefix, user.nick, msg))

    @staticmethod
    def web_debug(data):
        debug('web_debug: ' + repr(data))

### Channels: StandardChannel, StatusChannel, SpecialChannel

class Channel:
    def __init__(self, name):
        self.name = name
        self.topic = ''
        self.mode = 'n'
        self.members = {}

    def __repr__(self):
        return repr({k: v for k, v in self.__dict__.items() if k in ('name',)})

    @property
    def prefix(self):
        return self.name

    def log(self, source, fmt, *args):
        info('%s %s '+fmt, self.name, source.nick, *args)

    def multicast_group(self, source):
        return self.members.keys()

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
        self.on_names_impl(client, self.members.items())

    def on_names_impl(self, client, items):
        names = []
        for u, mode in items:
            nick = u.nick
            prefix = ''
            while 1:
                if 'o' in mode:
                    prefix += '@'
                    if 'multi-prefix' not in client.capabilities:
                        break
                if 'h' in mode:
                    prefix += '%'
                    if 'multi-prefix' not in client.capabilities:
                        break
                if 'v' in mode:
                    prefix += '+'
                    if 'multi-prefix' not in client.capabilities:
                        break
                break
            names.append(prefix+nick)
        buf = ''
        bytelen = 0
        maxlen = 510-1-len(server.name)-5-len(client.nick.encode())-3-len(self.name.encode())-2
        for name in names:
            if bytelen+1+len(name.encode()) > maxlen:
                client.reply('353 {} = {} :{}', client.nick, self.name, buf)
                buf = ''
                bytelen = 0
            if buf:
                buf += ' '
                bytelen += 1
            buf += name
            bytelen += len(name.encode())
        if buf:
            client.reply('353 {} = {} :{}', client.nick, self.name, buf)
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
    def __init__(self, name):
        super().__init__(name)

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
        elif not server.has_nick(nick):
            client.err_usernotinchannel(nick, self.name)
        else:
            user = server.get_nick(nick)
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
            server.remove_channel(self.name)
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
            member.on_who_member(client, self)


# A special channel where each client can only see himself
class StatusChannel(Channel):
    instance = None

    def __init__(self):
        super().__init__('+wechat')
        self.topic = "Your friends are listed here. Messages wont't be broadcasted to them. Type 'help' to see available commands"
        assert not StatusChannel.instance
        StatusChannel.instance = self

    def respond(self, client, fmt, *args):
        if args:
            client.write((':{} PRIVMSG {} :'+fmt).format(self.name, self.name, *args))
        else:
            client.write((':{} PRIVMSG {} :').format(self.name, self.name)+fmt)

    def multicast_group(self, source):
        return (x for x in self.members if isinstance(x, Client))

    def on_notice_or_privmsg(self, client, command, msg):
        if client not in self.members:
            client.err_notonchannel(self.name)
            return
        if msg == 'help':
            self.respond(client, 'help')
            self.respond(client, '  display this help')
            self.respond(client, 'eval expression')
            self.respond(client, '  eval a Python expression')
            self.respond(client, 'logout')
            self.respond(client, '  logout wx.qq.com')
            self.respond(client, 'reload')
            self.respond(client, '  reload wx.qq.com. The browser may pop up a confirm window')
            self.respond(client, 'reload_contact $name')
            self.respond(client, '  reload contact info in case of no such nick/channel in privmsg, and use __all__ as name if you want to reload all')
            self.respond(client, 'status [pattern]')
            self.respond(client, '  show contacts/channels')
        elif msg == 'logout':
            web.logout()
        elif msg == 'reload':
            web.reload()
        elif msg.startswith('status'):
            pattern = None
            ary = msg.split(' ', 1)
            if len(ary) > 1:
                pattern = ary[1]
            self.respond(client, 'IRC channels:')
            for name, room in server.channels.items():
                if pattern is not None and pattern not in name: continue
                if isinstance(room, StandardChannel):
                    self.respond(client, '  ' + name)
            self.respond(client, '{} Friends:', im_name)
            for name, user in server.nick2special_user.items():
                if user.is_friend:
                    if pattern is not None and not (pattern in name or pattern in user.record.get('Nick', '')): continue
                    line = name + ': friend ('
                    line += ', '.join([k + ':' + repr(v) for k, v in user.record.items() if k in ['Alias', 'Nick']])
                    line += ')'
                    self.respond(client, '  ' + line)
            self.respond(client, '{} Rooms:', im_name)
            for name, room in server.name2special_room.items():
                if pattern is not None and pattern not in name: continue
                self.respond(client, '  {} {}'.format(name, room.record.get('NickName', '')))
        elif msg.startswith('reload_contact'):
            who = None
            ary = msg.split(' ', 1)
            if len(ary) > 1:
                who = ary[1]
            if not who:
                self.respond(client, 'reload_contact <name>')
            else:
                web.reload_contact(who)
        elif msg.startswith('web_eval'):
            expr = None
            ary = msg.split(' ', 1)
            if len(ary) > 1:
                expr = ary[1]
            if not expr:
                self.respond(client, 'None')
            else:
                web.web_eval(expr)
                self.respond(client, 'expr sent, please use debug log to view eval result')
        else:
            m = re.match(r'eval (.+)$', msg.strip())
            if m:
                try:
                    r = pprint.pformat(eval(m.group(1)))
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
            self.members[member] = 'o'
            super().on_join(member)
        else:
            if member in self.members:
                return False
            member.enter(self)
            self.join_event(member)
            if member.is_friend:
                self.voice_event(member)
                self.members[member] = 'v'
            else:
                self.members[member] = ''
        return True

    def on_part(self, member, msg=None):
        if isinstance(member, Client):
            if member not in self.members:
                member.err_notonchannel(self.name)
                return False
            self.part_event(member, msg)
            del self.members[member]
        else:
            if member not in self.members:
                return False
            self.part_event(member, msg)
            del self.members[member]
        member.leave(self)
        return True

    def on_who(self, client):
        if client in self.members:
            client.on_who_member(client, self)


class SpecialChannel(Channel):
    def __init__(self, record):
        super().__init__(None)
        self.username = record['UserName']
        self.record = {}
        self.joined = {}      # `client` has not joined
        self.explicit_parted = set()
        # For large chatrooms, record['MemberList']['Uin'] is very likely
        # to be 0, so the owner is hard to determine.
        # If the owner is determined, he/she is the only op
        self.update(record)
        self.log_file = None
        self.privmsg_seq = 0
        self.privmsg_text = ''

    def __repr__(self):
        return repr({k: v for k, v in self.__dict__.items()
            if k in ('name', 'username')})

    @property
    def nick(self):
        return self.name

    def update(self, record):
        for k, v in record.items():
            if k not in self.record or v:
                self.record[k] = v
        if len(self.topic) and not record['Nick']:
            return
        self.topic = record['Nick']
        old_name = getattr(self, 'name', None)
        base = options.special_channel_prefix + irc_escape(self.topic)
        if base == options.special_channel_prefix:
            base += '.'.join(member.nick for member in self.members)[:20]
        suffix = ''
        while 1:
            name = base+suffix
            if name == old_name or not server.has_channel(name):
                break
            suffix = str(int(suffix or 0)+1)
        if name != old_name:
            # PART -> rename -> JOIN to notify the IRC client
            joined = [client for client in server.auth_clients() if client in self.joined]
            for client in joined:
                self.on_part(client, 'Changing name')
            self.name = name
            for client in joined:
                self.on_join(client)

    def update_detail(self, record):
        if isinstance(record.get('MemberList'), list):
            owner_uin = record.get('OwnerUin', -1)
            seen = {}
            seen_groupalias = {}
            for member in record['MemberList']:
                user = server.ensure_special_user(member)
                if user is not server:
                    if owner_uin > 0 and owner_uin == user.uin:
                        seen[user] = 'o'
                    elif user.is_friend:
                        seen[user] = 'v'
                    else:
                        seen[user] = ''
                    # Group Alias if not empty
                    seen_groupalias[user] = member.get('DisplayName', '')
            for user in self.members.keys() - seen.keys():
                self.on_part(user, self.name)
            for user in seen.keys() - self.members.keys():
                self.on_join(user)
            for user, groupalias in seen_groupalias.items():
                user.channel2nick[self] = groupalias
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
        return self.joined.keys()

    def set_umode(self, user, m):
        if user in self.joined:
            self.joined[user] = m+self.joined[user].replace(m, '')
        elif user in self.members:
            self.members[user] = m+self.members[user].replace(m, '')

    def unset_umode(self, user, m):
        if user in self.joined:
            self.joined[user] = self.joined[user].replace(m, '')
        elif user in self.members:
            self.members[user] = self.members[user].replace(m, '')

    def on_delete(self):
        joined = list(self.joined.keys())
        for client in list(self.joined.keys()):
            self.on_part(client, 'Deleted')
        for member in list(self.members.keys()):
            member.leave(self)
        del server.username2special_room[self.username]
        del server.name2special_room[irc_lower(self.name)]

    def on_mode(self, client, *args):
        if len(args):
            if args[0] == '+m':
                self.mode = 'm'+self.mode.replace('m', '')
                self.event(client, 'MODE', '{} {}', self.name, args[0])
            elif args[0] == '-m':
                self.mode = self.mode.replace('m', '')
                self.event(client, 'MODE', '{} {}', self.name, args[0])
            elif re.match('[-+]', args[0]):
                client.err_unknownmode(args[0][1] if len(args[0]) > 1 else '')
            else:
                client.err_unknownmode(args[0][0] if len(args[0]) else '')
        else:
            client.rpl_channelmodeis(self.name, self.mode)

    def on_names(self, client):
        self.on_names_impl(client, chain(self.joined.items(), self.members.items()))

    def on_notice_or_privmsg(self, client, command, text):
        irc_privmsg(client, command, self, text)

    def on_invite(self, client, nick):
        if server.has_special_user(nick):
            user = server.get_special_user(nick)
            #if user in self.members:
            #    client.err_useronchannel(nick, self.name)
            if not user.is_friend:
                client.err_nosuchnick(nick)
            else:
                web.add_member(self.username, user.username)
        else:
            client.err_nosuchnick(nick)

    def on_join(self, member):
        if isinstance(member, Client):
            if member in self.joined:
                return False
            self.joined[member] = ''
            self.explicit_parted.discard(member)
            super().on_join(member)
        else:
            if member in self.members:
                return False
            self.members[member] = ''
            member.enter(self)
            self.join_event(member)
        return True

    def on_kick(self, client, nick, reason):
        if server.has_special_user(nick):
            user = server.get_special_user(nick)
            web.del_member(self.username, user.username)
        else:
            client.err_usernotinchannel(nick, self.name)

    def on_part(self, member, msg=None):
        if isinstance(member, Client):
            if member not in self.joined:
                member.err_notonchannel(self.name)
                return False
            if msg:  # not msg implies being disconnected/kicked/...
                self.part_event(member, msg)
            del self.joined[member]
            self.explicit_parted.add(member)
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
                web.mod_topic(self.username, new)
            else:
                client.err_nochanmodes(self.name)
        else:
            super().on_topic(client, new)

    def on_who(self, client):
        members = tuple(self.members)+(client,)
        for member in members:
            member.on_who_member(client, self)


class Client:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        peer = writer.get_extra_info('socket').getpeername()
        self.host = peer[0]
        if self.host[0] == ':':
            self.host = '[{}]'.format(self.host)
        self.user = None
        self.nick = None
        self.registered = False
        self.mode = ''
        self.channels = {}             # joined, name -> channel
        self.capabilities = set()
        self.authenticated = False

    def enter(self, channel):
        self.channels[irc_lower(channel.name)] = channel

    def leave(self, channel):
        del self.channels[irc_lower(channel.name)]

    def auto_join(self, room):
        for regex in options.ignore or []:
            if re.search(regex, room.name):
                return
        for regex in options.ignore_topic or []:
            if re.search(regex, room.topic):
                return
        room.on_join(self)

    def is_in_channel(self, name):
        return irc_lower(name) in self.channels

    def disconnect(self, quitmsg):
        if quitmsg:
            self.write('ERROR :{}'.format(quitmsg))
            self.message_related(False, ':{} QUIT :{}', self.prefix, quitmsg)
        if self.nick is not None:
            info('Disconnected from %s', self.prefix)
        try:
            self.writer.write_eof()
            self.writer.close()
        except:
            pass
        if self.nick is None:
            return
        channels = list(self.channels.values())
        for channel in channels:
            channel.on_part(self, None)
        server.remove_nick(self.nick)
        self.nick = None
        server.clients.discard(self)

    def reply(self, msg, *args):
        '''Respond to the client's request'''
        self.write((':{} '+msg).format(server.name, *args))

    def write(self, msg):
        try:
            self.writer.write(msg.encode()+b'\r\n')
        except:
            pass

    def status(self, msg):
        '''A status message from the server'''
        self.write(':{} NOTICE {} :{}'.format(server.name, server.name, msg))

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

    def err_cannotsendtochan(self, channelname, text):
        self.reply('404 {} {} :{}', self.nick, channelname, text or 'Cannot send to channel')

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

    def err_unknownmode(self, mode):
        self.reply("472 {} {} :is unknown mode char to me", self.nick, mode)

    def err_nochanmodes(self, channelname):
        self.reply("477 {} {} :Channel doesn't support modes", self.nick, channelname)

    def err_chanoprivsneeded(self, channelname):
        self.reply("482 {} {} :You're not channel operator", self.nick, channelname)

    def err_umodeunknownflag(self):
        self.reply('501 {} :Unknown MODE flag', self.nick)

    def message_related(self, include_self, fmt, *args):
        '''Send a message to related clients which source is self'''
        line = fmt.format(*args)
        clients = [c for c in server.clients if c != self]
        if include_self:
            clients.append(self)
        for client in clients:
            client.write(line)

    def register(self):
        if self.registered:
            return
        if self.user and self.nick and (not (options.irc_password or options.sasl_password) or self.authenticated):
            self.registered = True
            info('%s registered', self.prefix)
            self.reply('001 {} :Hi, welcome to IRC', self.nick)
            self.reply('002 {} :Your host is {}', self.nick, server.name)
            self.reply('005 {} PREFIX=(ohv)@%+ CHANTYPES=!#&+ CHANMODES=,,,m SAFELIST :are supported by this server', self.nick)
            Command.lusers(self)
            Command.motd(self)

            Command.join(self, StatusChannel.instance.name)
            StatusChannel.instance.respond(self, 'Visit wx.qq.com and then you will see your friend list in this channel')

    def handle_command(self, command, args):
        cmd = irc_lower(command)
        if cmd == 'pass':
            cmd = cmd+'_'
        if type(Command.__dict__.get(cmd)) != staticmethod:
            self.err_unknowncommand(command)
            return
        fn = getattr(Command, cmd)
        if not (cmd_use_case.get(cmd, 2) & (2 if self.registered else 1)):
            self.err_unknowncommand(command)
            return
        try:
            ba = inspect.signature(fn).bind(self, *args)
        except TypeError:
            self.err_needmoreparams(command)
            return
        fn(*ba.args)

    async def handle_irc(self):
        sent_ping = False
        while 1:
            try:
                line = await asyncio.wait_for(
                    self.reader.readline(), loop=server.loop,
                    timeout=options.heartbeat)
            except asyncio.TimeoutError:
                if sent_ping:
                    self.disconnect('ping timeout')
                    return
                else:
                    sent_ping = True
                    self.write('PING :'+server.name)
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
            try:
                self.handle_command(command, args)
            except:
                traceback.print_exc()
                self.disconnect('client error')

    def ctcp(self, peer, msg):
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
            web.send_file(peer.username, filename, body)

        async def download_wrap():
            try:
                await asyncio.wait_for(download(), options.dcc_send_download_timeout)
            except asyncio.TimeoutError:
                self.status('Downloading of DCC SEND timeout')

        if len(msg) > 2 and msg[0] == '\1' and msg[-1] == '\1':
            # VULNERABILITY used as proxy
            try:
                dcc_, send_, filename, ip, port, size = msg[1:-1].split(' ')
                ip = socket.gethostbyname(str(int(ip)))
                size = int(size)
                assert dcc_ == 'DCC' and send_ == 'SEND'
                if 0 < size <= options.dcc_send:
                    server.loop.create_task(download())
                else:
                    self.status('DCC SEND: invalid size of {}, (0,{}] is acceptable'.format(
                            filename, options.dcc_send))
            except:
                pass
            return True
        return False

    def on_who_member(self, client, channel):
        client.reply('352 {} {} {} {} {} {} H :0 {}', client.nick, channel.name,
                     self.user, self.host, server.name,
                     self.nick, self.realname)

    def on_whois(self, client):
        client.reply('311 {} {} {} {} * :{}', client.nick, self.nick,
                     self.user, self.host, self.realname)
        client.reply('319 {} {} :{}', client.nick, self.nick,
                     ' '.join(name for name in
                              client.channels.keys() & self.channels.keys()))

    def on_websocket_open(self, peername):
        status = StatusChannel.instance
        #self.status('WebSocket client connected from {}'.format(peername))

    def on_websocket_close(self, peername):
        status = StatusChannel.instance
        # PART all special channels, these chatrooms will be garbage collected
        channels = list(self.channels.values())
        for room in channels:
            if room != status:
                room.on_part(self, 'WebSocket client disconnection')

        # instead of flooding +wechat with massive PART messages,
        # take the shortcut by rejoining the client
        in_status = self in status.members
        if in_status:
            status.on_part(self, 'WebSocket client disconnected from {}'.format(peername))
        members = list(status.members)
        for x in members:
            if isinstance(x, SpecialUser):
                status.on_part(x)
        if in_status:
            status.on_join(self)


class BrandServ:
    def __init__(self):
        self.log_file = None

    @property
    def nick(self):
        return BrandServ.__name__

    @property
    def prefix(self):
        return '{}!{}@services.'.format(self.nick, self.nick)


class SpecialUser:
    def __init__(self, record, friend):
        self.username = record['UserName']
        self.channel2nick = {}
        self.is_friend = False
        self.record = {}
        self.uin = 0
        self.update(record, friend)
        self.log_file = None
        self.privmsg_seq = 0
        self.privmsg_text = ''

    @property
    def prefix(self):
        return '{}!{}@{}'.format(self.nick, self.username.replace('@', ''), im_name)

    def preferred_nick(self):
        if self.username.startswith('@'):
            return self.record['Nick']
        # special contacts, e.g. filehelper
        return self.username

    def alias(self):
        return self.record.get('Alias') or self.record.get('Nick', '')

    def update(self, record, friend):
        for k, v in record.items():
            if k not in self.record or v:
                self.record[k] = v
        uin = self.record.get('Uin', 0)
        if uin > 0:
            self.uin = uin
        old_nick = getattr(self, 'nick', None)
        base = irc_escape_nick(self.preferred_nick()) or 'Guest'
        suffix = ''
        while 1:
            nick = base+suffix
            if nick and (nick == old_nick or
                    not (server.has_nick(nick) or irc_lower(nick) in options.irc_nicks)):
                break
            suffix = str(int(suffix or 0)+1)
        if nick != old_nick:
            for channel in self.channel2nick:
                channel.nick_event(self, nick)
            self.nick = nick
        # friend
        if friend > 0:
            if not self.is_friend:
                self.is_friend = True
                StatusChannel.instance.on_join(self)
                for channel in self.channel2nick:
                    if isinstance(channel, SpecialChannel):
                        channel.members[self] = 'v'
                        channel.voice_event(self)
        # non_friend
        elif friend < 0:
            if self.is_friend:
                self.is_friend = False
                StatusChannel.instance.on_part(self)
                for channel in self.channel2nick:
                    if isinstance(channel, SpecialChannel):
                        channel.members[self] = ''
                        channel.devoice_event(self)
        # unsure

    def enter(self, channel):
        self.channel2nick[channel] = ''

    def leave(self, channel):
        del self.channel2nick[channel]

    def on_notice_or_privmsg(self, client, command, text):
        irc_privmsg(client, command, self, text)

    def on_who_member(self, client, channel):
        if channel in self.channel2nick:
            nick = self.channel2nick[channel]
        else:
            nick = ''
        client.reply('352 {} {} {} {} {} {} H :0 {}', client.nick, channel.name,
                     self.username, im_name, server.name, self.nick, nick or self.alias())

    def on_whois(self, client):
        client.reply('311 {} {} {} {} * :{}', client.nick, self.nick,
                     self.username, im_name, self.alias())


class Server:
    valid_nickname = re.compile(r"^[][\`_^{|}A-Za-z][][\`_^{|}A-Za-z0-9-]{0,50}$")
    # initial character `+` is reserved for StatusChannel
    # initial character `&` is reserved for SpecialChannel
    valid_channelname = re.compile(r"^[#!][^\x00\x07\x0a\x0d ,:]{0,50}$")

    def __init__(self):
        global server
        server = self
        status = StatusChannel()
        self.channels = {status.name: status}
        self.name = 'wechatircd.maskray.me'
        self.nicks = {}
        self.clients = weakref.WeakSet()
        self.log_file = None
        self._boot = datetime.now()
        self.services = ('BrandServ', 'ChanServ',)

        self.username = ''
        self.name2special_room = {}      # name -> WeChat chatroom
        self.username2special_room = {}  # UserName -> SpecialChannel
        self.nick2special_user = {}      # nick -> IRC user or WeChat user (friend or room contact)
        self.username2special_user = {}  # UserName -> SpecialUser

    def _accept(self, reader, writer):
        try:
            client = Client(reader, writer)
            self.clients.add(client)
            task = self.loop.create_task(client.handle_irc())
            def done(task):
                client.disconnect(None)

            task.add_done_callback(done)
        except Exception as e:
            traceback.print_exc()

    def auth_clients(self):
        return (c for c in self.clients if c.nick)

    def preferred_client(self):
        n = len(self.clients)
        opt, optv = None, n+2
        for c in self.clients:
            if c.nick:
                try:
                    v = options.irc_nicks.index(c.nick)
                except ValueError:
                    v = n+1 if c.nick.endswith('bot') else n
                if v < optv:
                    opt, optv = c, v
        return opt

    def has_channel(self, name):
        x = irc_lower(name)
        return x in self.channels or x in self.name2special_room

    def has_nick(self, nick):
        x = irc_lower(nick)
        return x in self.nicks or x in self.nick2special_user

    def has_special_room(self, name):
        return irc_lower(name) in self.name2special_room

    def has_special_user(self, nick):
        return irc_lower(nick) in self.nick2special_user

    def get_channel(self, name):
        x = irc_lower(name)
        return self.channels[x] if x in self.channels else self.name2special_room[x]

    def get_nick(self, nick):
        x = irc_lower(nick)
        return self.nicks[x] if x in self.nicks else self.nick2special_user[x]

    def get_special_user(self, nick):
        return self.nick2special_user[irc_lower(nick)]

    def get_special_room(self, name):
        return self.name2special_room[irc_lower(name)]

    def remove_special_user(self, nick):
        del self.nick2special_user[irc_lower(nick)]

    # IRC channel or special chatroom
    def ensure_channel(self, channelname):
        if self.has_channel(channelname):
            return self.channels[irc_lower(channelname)]
        if not Server.valid_channelname.match(channelname):
            raise ValueError
        channel = StandardChannel(channelname)
        self.channels[irc_lower(channelname)] = channel
        return channel

    def ensure_special_room(self, record):
        debug('ensure_special_room %r', record)
        assert isinstance(record['UserName'], str)
        assert isinstance(record['Nick'], str)
        assert isinstance(record.get('OwnerUin', -1), int)
        if record['UserName'] in self.username2special_room:
            room = self.username2special_room[record['UserName']]
            del self.name2special_room[irc_lower(room.name)]
            room.update(record)
        else:
            room = SpecialChannel(record)
            self.username2special_room[room.username] = room
            if options.join == 'all':
                self.auto_join(room)
        self.name2special_room[irc_lower(room.name)] = room
        return room

    def ensure_special_user(self, record, friend=0):
        assert isinstance(record['UserName'], str)
        assert isinstance(record['Nick'], str)
        assert isinstance(record.get('Uin', 0), int)
        if record['UserName'] == self.username:
            uin = record.get('Uin', 0)
            if uin:
                self.uin = uin
            return self
        if record['UserName'] in self.username2special_user:
            user = self.username2special_user[record['UserName']]
            self.remove_special_user(user.nick)
            user.update(record, friend)
        else:
            user = SpecialUser(record, friend)
            self.username2special_user[user.username] = user
        self.nick2special_user[irc_lower(user.nick)] = user
        return user

    def remove_channel(self, channelname):
        del self.channels[irc_lower(channelname)]

    def change_nick(self, client, new):
        lower = irc_lower(new)
        if self.has_nick(new) or lower in self.services:
            client.err_nicknameinuse(new)
        elif not Server.valid_nickname.match(new):
            client.err_errorneusnickname(new)
        else:
            if client.nick:
                info('%s changed nick to %s', client.prefix, new)
                self.remove_nick(client.nick)
                client.message_related(True, ':{} NICK {}', client.prefix, new)
            self.nicks[lower] = client
            client.nick = new

    def remove_nick(self, nick):
        del self.nicks[irc_lower(nick)]

    def start(self, loop, tls):
        self.loop = loop
        self.servers = []
        for i in options.irc_listen if options.irc_listen else options.listen:
            self.servers.append(loop.run_until_complete(
                asyncio.streams.start_server(self._accept, i, options.irc_port, ssl=tls)))

    def stop(self):
        for i in self.servers:
            i.close()
            self.loop.run_until_complete(i.wait_closed())

    ## WebSocket
    def on_websocket(self, data):
        command = data['command']
        if type(SpecialCommands.__dict__.get(command)) == staticmethod:
            getattr(SpecialCommands, command)(data)

    def on_websocket_close(self, peername):
        for client in self.auth_clients():
            client.on_websocket_close(peername)
        self.name2special_room.clear()
        self.username2special_room.clear()
        self.nick2special_user.clear()
        self.username2special_user.clear()
        web.recent_messages.clear()
        web.id2message.clear()


def main():
    ap = ArgParser(description='wechatircd brings wx.qq.com to IRC clients')
    ap.add('-c', '--config', is_config_file=True, help='config file path')
    ap.add_argument('-d', '--debug', action='store_true', help='run ipdb on uncaught exception')
    ap.add_argument('--dcc-send', type=int, default=10*1024*1024, help='size limit receiving from DCC SEND. 0: disable DCC SEND')
    ap.add_argument('--heartbeat', type=int, default=30, help='time to wait for IRC commands. The server will send PING and close the connection after another timeout of equal duration if no commands is received.')
    ap.add_argument('--http-cert', help='TLS certificate for HTTPS/WebSocket over TLS. You may concatenate certificate+key, specify a single PEM file and omit `--http-key`. Use HTTP if neither --http-cert nor --http-key is specified')
    ap.add_argument('--http-key', help='TLS key for HTTPS/WebSocket over TLS')
    ap.add_argument('--http-listen', nargs='*',
                    help='HTTP/WebSocket listen addresses (overriding --listen)')
    ap.add_argument('--http-port', type=int, default=9000, help='HTTP/WebSocket listen port, default: 9000')
    ap.add_argument('--http-root', default=os.path.dirname(__file__), help='HTTP root directory (serving injector.js)')
    ap.add_argument('--http-url',
                     help='If specified, display media links as http://localhost:9000/media/$id ; if not, `https://wx.qq.com/cgi-bin/...`')
    ap.add_argument('-i', '--ignore', nargs='*',
                    help='list of ignored regex, do not auto join to a '+im_name+' chatroom whose channel name(generated from the Group Name) matches')
    ap.add_argument('--ignore-brand', action='store_true', help='ignore messages from Subscription Accounts')
    ap.add_argument('-I', '--ignore-topic', nargs='*',
                    help='list of ignored regex, do not auto join to a '+im_name+' chatroom whose Group Name matches')
    ap.add_argument('--irc-cert', help='TLS certificate for IRC over TLS. You may concatenate certificate+key, specify a single PEM file and omit `--irc-key`. Use plain IRC if neither --irc-cert nor --irc-key is specified')
    ap.add_argument('--irc-key', help='TLS key for IRC over TLS')
    ap.add_argument('--irc-listen', nargs='*',
                    help='IRC listen addresses (overriding --listen)')
    ap.add_argument('--irc-nicks', nargs='*', default=[],
                    help='reserved nicks for clients')
    ap.add_argument('--irc-password', default='', help='Set the IRC connection password')
    ap.add_argument('--irc-port', type=int, default=6667,
                    help='IRC server listen port. defalt: 6667')
    ap.add_argument('-j', '--join', choices=['all', 'auto', 'manual', 'new'], default='auto',
                    help='join mode for '+im_name+' chatrooms. all: join all after connected; auto: join after the first message arrives; manual: no automatic join; new: join whenever messages arrive (even if after /part); default: auto')
    ap.add_argument('-l', '--listen', nargs='*', default=['127.0.0.1'],
                    help='IRC/HTTP/WebSocket listen addresses, default: 127.0.0.1')
    ap.add_argument('--logger-ignore', nargs='*', help='list of ignored regex, do not log contacts/chatrooms whose names match')
    ap.add_argument('--logger-mask', help='WeeChat logger.mask.irc')
    ap.add_argument('--logger-time-format', default='%H:%M', help='WeeChat logger.file.time_format')
    ap.add_argument('--paste-wait', type=float, default=0.1, help='lines will be hold for up to $paste_wait seconds before sending, lines in this interval will be packed to a multiline message')
    ap.add_argument('-q', '--quiet', action='store_const', const=logging.WARN, dest='loglevel')
    ap.add_argument('--sasl-password', default='', help='Set the SASL password')
    ap.add_argument('--special-channel-prefix', choices=('&', '!', '#', '##'), default='&', help='prefix for SpecialChannel')
    ap.add_argument('-v', '--verbose', action='store_const', const=logging.DEBUG, dest='loglevel')
    global options
    options = ap.parse_args()
    options.irc_nicks = [irc_lower(x) for x in options.irc_nicks]

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
    server = Server()
    web = Web(http_tls)

    server.start(loop, irc_tls)
    web.start(options.http_listen if options.http_listen else options.listen,
              options.http_port, loop)
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        server.stop()
        web.stop()
        loop.stop()


if __name__ == '__main__':
    sys.exit(main())
