[简体中文](README.zhs.md)

# wechatircd

wechatircd injects JavaScript (`injector.js`) to wx.qq.com, which uses WebSocket to communicate with an IRC server (`wechatircd.py`), thus enable IRC clients connected to the server to send and receive messages from WeChat.

```
           IRC               WebSocket                 HTTPS
IRC client --- wechatircd.py --------- browser         ----- wx.qq.com
                                       injector.user.js
                                       injector.js
```

## Installation

`>=python-3.5`

`pip install -r requirements.txt`

### Arch Linux

- `yaourt -S wechatircd-git`. It will generate a self-signed key/certificate pair in `/etc/wechatircd/` (see below).
- Import `/etc/wechatircd/cert.pem` to the browser (see below).
- `systemctl start wechatircd`, which runs `/usr/bin/wechatircd --http-cert /etc/wechatircd/cert.pem --http-key /etc/wechatircd/key.pem --http-root /usr/share/wechatircd`.

The IRC server listens on 127.0.0.1:6667 (IRC) and 127.0.0.1:9000 (HTTPS + WebSocket over TLS) by default.

If you run the server on another machine, it is recommended to set up IRC over TLS and an IRC connection password: `/usr/bin/wechatircd --http-cert /etc/wechatircd/cert.pem --http-key /etc/wechatircd/key.pem --http-root /usr/share/wechatircd --irc-cert /path/to/irc.key --irc-key /path/to/irc.cert --irc-password yourpassword`.

You can reuse the HTTPS certificate+key as IRC over TLS certificate+key. If you use WeeChat and find it difficult to set up a valid certificate (gnutls checks the hostname), type the following lines in WeeChat:
```
set irc.server.wechat.ssl on`
set irc.server.wechat.ssl_verify off
set irc.server.wechat.password yourpassword`
```

`aur/python-aiohttp-1.0.5-1` may not work, please install `archlinuxcn/python-aiohttp-1.1.5-1` or newer.

### Not Arch Linux

- Generate a self-signed private key/certificate pair with `openssl req -newkey rsa:2048 -nodes -keyout key.pem -x509 -out cert.pem -subj '/CN=127.0.0.1' -dates 9999`.
- Import `cert.pem` to the browser.
- `./wechatircd.py --http-cert cert.pem --http-key key.pem`

### Import self-signed certificate to the browser

Chrome/Chromium

- Visit `chrome://settings/certificates`，import `cert.pem`，click the `Authorities` tab，select the `127.0.0.1` certificate, Edit->Trust this certificate for identifying websites.
- Install extension Tampermonkey, install <https://github.com/MaskRay/wechatircd/raw/master/injector.user.js>. It will inject <https://127.0.0.1:9000/injector.js> to <https://wx.qq.com>.

Firefox

- Install extension Greasemonkey，install the user script.
- Visit <https://127.0.0.1:9000/injector.js>, Firefox will show "Your connection is not secure", Advanced->Add Exception->Confirm Security Exception

![](https://maskray.me/static/2016-02-21-wechatircd/run.jpg)

The server listens on 127.0.0.1:9000 (HTTPS + WebSocket over TLS) by default, which can be overrided with the `--web-port 10000` option. You need to change the userscript to use other ports.

## Usage

- Run `wechatircd.py` to start the IRC + HTTPS + WebSocket server.
- Visit <https://wx.qq.com>, the injected JavaScript will create a WebSocket connection to the server
- Connect to 127.0.0.1:6667 in your IRC client

You will join `+wechat` channel automatically and find your contact list there. Some commands are available:

- `help`
- `status`, mutual contact list、group/supergroup list

Nicks of contacts are generated from `RemarkName` or `DisplayName`.

## Server options

- Join mode. There are three modes, the default is `--join auto`: join the channel upon receiving the first message, no rejoin after issuing `/part` and receiving messages later. The other three are `--join all`: join all the channels; `--join manual`: no automatic join; `--join new`: like `auto`, but rejoin when new messages arrive even if after `/part`.
- Groups that should not join automatically. This feature supplements join mode.
  + `--ignore 'fo[o]' bar`, do not auto join chatrooms whose channel name(generated from DisplayName) matches regex `fo[o]` or `bar`
  + `--ignore-display-name 'fo[o]' bar`, do not auto join chatrooms whose DisplayName matches regex `fo[o]` or `bar`
- HTTP/WebSocket related options
  + `--http-cert cert.pem`, TLS certificate for HTTPS/WebSocket. You may concatenate certificate+key, specify a single PEM file and omit `--http-key`. Use HTTP if neither --http-cert nor --http-key is specified.
  + `--http-key key.pem`, TLS key for HTTPS/WebSocket.
  + `--http-listen 127.1 ::1`, change HTTPS/WebSocket listen address to `127.1` and `::1`, overriding `--listen`.
  + `--http-port 9000`, change HTTPS/WebSocket listen port to 9000.
  + `--http-root .`, the root directory to serve `injector.js`.
- `-l 127.0.0.1`, change IRC/HTTP/WebSocket listen address to `127.0.0.1`.
- IRC related options
  + `--irc-cert cert.pem`, TLS certificate for IRC over TLS. You may concatenate certificate+key, specify a single PEM file and omit `--irc-key`. Use plain IRC if neither --irc-cert nor --irc-key is specified.
  + `--irc-key key.pem`, TLS key for IRC over TLS.
  + `--irc-listen 127.1 ::1`, change IRC listen address to `127.1` and `::1`, overriding `--listen`.
  + `--irc-password pass`, set the connection password to `pass`.
  + `--irc-port 6667`, IRC server listen port.
- Server side log
  + `--logger-ignore '&test0' '&test1'`, list of ignored regex, do not log contacts/groups whose names match
  + `--logger-mask '/tmp/wechat/$channel/%Y-%m-%d.log'`, format of log filenames
  + `--logger-time-format %H:%M`, time format of server side log

## IRC features

- Standard IRC channels have names beginning with `#`.
- WeChat groups have names beginning with `&`. The channel name is generated from the group title. `SpecialChannel#update`
- Contacts have modes `+v` (voice, usually displayed with a prefix `+`). `SpecialChannel#update_detail`

`server-time` extension from IRC version 3.1, 3.2. `wechatircd.py` includes the timestamp (obtained from JavaScript) in messages to tell IRC clients that the message happened at the given time. See <http://ircv3.net/irc/>. See<http://ircv3.net/software/clients.html> for Client support of IRCv3.

Configuration for WeeChat:
```
/set irc.server_default.capabilities "account-notify,away-notify,cap-notify,multi-prefix,server-time,znc.in/server-time-iso,znc.in/self-message"
```

Supported IRC commands:

- `/cap`, supported capabilities.
- `/dcc send $nick/$channel $filename`, send image or file。This feature borrows the command `/dcc send` which is well supported in IRC clients. See <https://en.wikipedia.org/wiki/Direct_Client-to-Client#DCC_SEND>.
- `/invite $nick [$channel]`, invite a contact to the group.
- `/kick $nick`, delete a group member. You must be the group leader to do this. Due to the defect of the Web client, you may not receive notifcations about the change of members.
- `/list`, list groups.
- `/mode +m`, no rejoin in `--join new` mode. `/mode -m` to revert.
- `/names`, update nicks in the channel.
- `/part $channel`, no longer receive messages from the channel. It just borrows the command `/part` and it will not leave the group.
- `/query $nick`, open a chat window with `$nick`.
- `/summon $nick $message`，add a contact.
- `/topic topic`, change the topic of a group. Because IRC does not support renaming of a channel, you will leave the channel with the old name and join a channel with the new name.
- `/who $channel`, see the member list.

Multi-line messages:

- `!m line0\nline1`
- `!html line0<br>line1`

![](https://maskray.me/static/2016-02-21-wechatircd/topic-kick-invite.jpg)

### Display

- `MSGTYPE_TEXT`，text, or invitation of voice/video call
- `MSGTYPE_IMG`，image, displayed as `[Image] $url`
- `MSGTYPE_VOICE`，audio, displayed as `[Voice] $url`
- `MSGTYPE_VIDEO`，video, displayed as `[Video] $url`
- `MSGTYPE_MICROVIDEO`，micro video?，displayed as `[MicroVideo] $url`
- `MSGTYPE_APP`，articles from Subscription Accounts, Red Packet, URL, ..., displayed as `[App] $title $url`

QQ emoji is displayed as `<img class="qqemoji qqemoji0" text="[Smile]_web" src="/zh_CN/htmledition/v2/images/spacer.gif">`, `[Smile]` in sent messages will be replaced to emoticon.

Emoji is rendered as `<img class="emoji emoji1f604" text="_web" src="/zh_CN/htmledition/v2/images/spacer.gif">`，it will be converted to a single character before delivered to the IRC client. Emoji may overlap as terminal emulators may not know emoji are of width 2，see [终端模拟器下使用双倍宽度多色Emoji字体](https://maskray.me/blog/2016-03-13-terminal-emulator-fullwidth-color-emoji).

## Changes in `injector.js`

Changes are marked with `//@`.

### Beginning of `webwxapp.js`

Create a WebSocket connection to the server and retry on failures.

### Send the contact list to the server periodically

Fetch contacts, groups and subscription accounts every 5 seconds, and send them to the server.

## `wechatircd.py`

Copied a lot of protocol related stuff from miniircd.

```
.
├── Web                      HTTP(s)/WebSocket server
├── Server                   IRC server
├── Channel
│   ├── StandardChannel      IRC channels
│   ├── StatusChannel        `+wechat`
│   └── SpecialChannel       WeChat groups
├── (User)
│   ├── Client               IRC clients
│   ├── SpecialUser          WeChat users
├── (IRCCommands)
│   ├── UnregisteredCommands available commands: CAP NICK PASS USER QUIT
│   ├── RegisteredCommands
```

## FAQ

### Motivation

- Replace the mobile client with your IRC client. See [WeeChat操作各种聊天软件](https://maskray.me/blog/2016-08-13-weechat-rules-all).
- Bot
- Log. It is difficult to export log from the mobile client <https://maskray.me/blog/2014-10-14-wechat-export>

If you cannot tolerant scanning QR codes with your phone everyday, see [无需每日扫码的IRC版微信和QQ：wechatircd、webqqircd](https://maskray.me/blog/2016-07-06-wechatircd-webqqircd-without-scanning-qrcode-daily).

## Fetch data & control wx.qq.com

Some special accounts' `UserName` do not have the `@` prefix: `newsapp,fmessage,filehelper,weibo,qqmail,fmessage`。Standard accounts' `UserName` start with `@`; Groups' `UserName` start with `@@`。`UserName` are different among sessions. `Uin` looks like an unique identifier, but most of the time its value is 0.
A group's `OwnerUin` is the owners's `Uin`，but most of the time `Uin` is 0.

My account
```javascript
angular.element(document.body).scope().account
```

List of all contacts
```javascript
angular.element($('#navContact')[0]).scope().allContacts
```

Delete a member from a group
```javascript
var injector = angular.element(document).injector()
# 这里获取了chatroomFactory，还可用于获取其他factory、service、controller等
var chatroomFactory = injector.get('chatroomFactory')
# 设置其中的`room`与`userToRemove`
chatroomFactory.delMember(room.UserName, userToRemove.UserName)`
```

Send a message to the current chat
```javascript
angular.element('pre:last').scope().editAreaCtn = "Hello，微信";
angular.element('pre:last').scope().sendTextMessage();
```

## References

- [miniircd](https://github.com/jrosdahl/miniircd)
- [RFC 2810: Internet Relay Chat: Architecture](https://tools.ietf.org/html/rfc2810)
- [RFC 2811: Internet Relay Chat: Channel Management](https://tools.ietf.org/html/rfc2811)
- [RFC 2812: Internet Relay Chat: Client Protocol](https://tools.ietf.org/html/rfc2812)
- [RFC 2813: Internet Relay Chat: Server Protocol](https://tools.ietf.org/html/rfc2813)
