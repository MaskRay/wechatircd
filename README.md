[简体中文](README.zhs.md)

# wechatircd [![IRC](https://img.shields.io/badge/IRC-freenode-yellow.svg)](https://webchat.freenode.net/?channels=wechatircd) [![Telegram](https://img.shields.io/badge/chat-Telegram-blue.svg)](https://t.me/wechatircd) [![Gitter](https://img.shields.io/badge/chat-Gitter-753a88.svg)](https://gitter.im/wechatircd/wechatircd)

wechatircd injects JavaScript (`injector.js`) to wx.qq.com, which uses WebSocket to communicate with an IRC server (`wechatircd.py`), thus enable IRC clients connected to the server to send and receive messages from WeChat, set topics, invite/delete members, ...

```
           IRC               WebSocket                 HTTPS
IRC client --- wechatircd.py --------- browser         ----- wx.qq.com
                                       injector.user.js
                                       injector.js
```

Discuss wechatircd by joining #wechatircd on freenode, or the [user group on Telegram](https://t.me/wechatircd).
[Video on using WeChat in WeeChat](https://asciinema.org/a/636dkay05bpzci1idf3e84y1y)

## Installation

- [Arch Linux](#arch-linux) or [Not Arch Linux](#not-arch-linux)
- [Userscript and self-signed certificate](#userscript-and-self-signed-certificate)
- [Usage](#usage)

### Arch Linux

- `yaourt -S wechatircd-git`. It will generate a self-signed key/certificate pair in `/etc/wechatircd/` (see below).
- Import `/etc/wechatircd/cert.pem` to the browser (see below).
- `systemctl start wechatircd`, which runs `/usr/bin/wechatircd --http-cert /etc/wechatircd/cert.pem --http-key /etc/wechatircd/key.pem --http-root /usr/share/wechatircd`. You may want to customize `/etc/systemd/system/wechatircd.service`.

`wechatircd.py` (the server) will listen on 127.0.0.1:6667 (IRC) and 127.0.0.1:9000 (HTTPS + WebSocket over TLS).

If you run the server on another machine, it is recommended to set up IRC over TLS and an IRC connection password with a few more options: `--irc-cert /path/to/irc.key --irc-key /path/to/irc.cert --irc-password yourpassword`. You can reuse the HTTPS certificate+key. If you use WeeChat and find it difficult to set up a valid certificate (gnutls checks the hostname), type the following lines in WeeChat:
```
set irc.server.wechat.ssl on
set irc.server.wechat.ssl_verify off
set irc.server.wechat.password yourpassword
```

### Not Arch Linux

- python >= 3.5
- `pip install -r requirements.txt`
- Generate a self-signed private key/certificate pair with `openssl req -newkey rsa:2048 -nodes -keyout key.pem -x509 -out cert.pem -subj '/CN=127.0.0.1' -days 9999`.
- Import `cert.pem` to the browser.
- `./wechatircd.py --http-cert cert.pem --http-key key.pem`

## Userscript and self-signed certificate

Chrome/Chromium

- Visit `chrome://settings/certificates`，import `cert.pem`，click the `Authorities` tab，select the `127.0.0.1` certificate, Edit->Trust this certificate for identifying websites.
- Install extension Tampermonkey, install <https://github.com/MaskRay/wechatircd/raw/master/injector.user.js>. It will inject <https://127.0.0.1:9000/injector.js> to <https://wx.qq.com>. You need to change `127.0.0.1:9000` if you want wechatircd to listen on another address.

Firefox

- Install extension Greasemonkey，install the userscript.
- Visit <https://127.0.0.1:9000/injector.js>, Firefox will show "Your connection is not secure", Advanced->Add Exception->Confirm Security Exception

![](https://maskray.me/static/2016-02-21-wechatircd/meow.jpg)

The server serves `injector.js` and WebSocket connections on 127.0.0.1:9000 by default, which can be overriden with `--http-listen 0.0.0.0 --http-port 9000`.

You can enable HTTPS in two ways:

- `--http-cert cert.pem --http-key key.pem` to make wechatircd serve HTTPS
- Omit `--http-cert --http-key` to make wechatircd serve HTTP, and use Nginx (with HTTPS enabled) as a reverse proxy. In this case, you need to pass `Host:` to wechatircd (`proxy_set_header Host $http_host;`) as it changes the WebSocket URL defined in `injector.js` according to `Host:` specified by the browser.

## Usage

- Run `wechatircd.py`
- Visit <https://wx.qq.com>, the injected JavaScript will create a WebSocket connection to the server
- Connect to 127.0.0.1:6667 in your IRC client

You will join `+wechat` channel automatically and find your contact list there. Some commands are available:

- `help`
- `eval`, eval a Python expression, such as: `eval server.nick2special_user` `eval server.name2special_room`
- `status`, show contacts/channels
- `reload_contact __all__`, reload all contact info in case of `no such nick/channel` in privmsg

The server can only be bound to one wx.qq.com account, however, you may have more than one IRC clients connected to the server.

## IRC features

- Standard IRC channels have names beginning with `#`.
- WeChat groups have names beginning with `&`. The channel name is generated from the group title. `SpecialChannel#update`
- Contacts have modes `+v` (voice, usually displayed with a prefix `+`). `SpecialChannel#update_detail`
- Multi-line messages: `!m line0\nline1`
- Multi-line messages: `!html line0<br>line1`
- `nick0: nick1: test` will be converted to `@GroupAlias0 @GroupAlias1 test`, where `GroupAlias0` is `My Alias in Group`/`Name` in profile/`WeChat ID` set by that user. It corresponds to `On-screen names` in the mobile application.
- Reply to the message at 12:34:SS: `@1234 !m multi\nline\nreply`, which will be sent as `「Re GroupAlias: text」text`
- Reply to the message at 12:34:56: `!m @123456 multi\nline\nreply`
- Reply to the penultimate message (your own messages are not counted) in this channel/chat: `@2 reply`
- Paste detection. Lines will be hold for up to 0.1 seconds before sending, lines in this interval will be packed to a multiline message
- `--http-url https://127.0.0.1:9000` if you want to shorten media URLs to something like `https://127.0.0.1:9000/media/0`

`!m `, `@3 `, `nick: ` can be arranged in any order.

For WeeChat, its anti-flood mechanism will prevent two user messages sent to IRC server in the same time. Disable anti-flood to enable paste detection.
```
/set irc.server.wechat.anti_flood_prio_high 0
```

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
- `/kill $nick [$reason]`, cause the connection of that client to be closed
- `/list`, list groups.
- `/mode +m`, no rejoin in `--join new` mode. `/mode -m` to revert.
- `/motd`, view latest 5 commits of this repo
- `/names`, update nicks in the channel.
- `/part [$channel]`, no longer receive messages from the channel. It just borrows the command `/part` and it will not leave the group.
- `/query $nick`, open a chat window with `$nick`.
- `/squit $any`, log out
- `/summon $nick $message`，add a contact.
- `/topic topic`, change the topic of a group. Because IRC does not support renaming of a channel, you will leave the channel with the old name and join a channel with the new name.
- `/who $channel`, see the member list.

![](https://maskray.me/static/2016-02-21-wechatircd/demo.jpg)

### Display

- `MSGTYPE_TEXT`，text, or invitation of voice/video call
- `MSGTYPE_IMG`，image, displayed as `[Image] $url`
- `MSGTYPE_VOICE`，audio, displayed as `[Voice] $url`
- `MSGTYPE_VIDEO`，video, displayed as `[Video] $url`
- `MSGTYPE_MICROVIDEO`，micro video?，displayed as `[MicroVideo] $url`
- `MSGTYPE_APP`，articles from Subscription Accounts, Red Packet, URL, ..., displayed as `[App] $title $url`

QQ emojis are displayed as `<img class="qqemoji qqemoji0" text="[Smile]_web" src="/zh_CN/htmledition/v2/images/spacer.gif">`, `[Smile]` in sent messages will be replaced to emoticon.

Emojis are rendered as `<img class="emoji emoji1f604" text="_web" src="/zh_CN/htmledition/v2/images/spacer.gif">`. Each emoji will be converted to a single character before delivered to the IRC client. Emojis may overlap as terminal emulators may not know emojis are of width 2，see [终端模拟器下使用双倍宽度多色Emoji字体](https://maskray.me/blog/2016-03-13-terminal-emulator-fullwidth-color-emoji).

## Server options

- `--config`, short option `-c`, config file path, see [config](config)
- HTTP/WebSocket related options
  + `--http-cert cert.pem`, TLS certificate for HTTPS/WebSocket. You may concatenate certificate+key, specify a single PEM file and omit `--http-key`. Use HTTP if neither `--http-cert` nor `--http-key` is specified.
  + `--http-key key.pem`, TLS key for HTTPS/WebSocket
  + `--http-listen 127.1 ::1`, change HTTPS/WebSocket listen address to `127.1` and `::1`, overriding `--listen`
  + `--http-port 9000`, change HTTPS/WebSocket listen port to 9000
  + `--http-root .`, the root directory to serve `injector.js`
  + `--http-url https://127.0.0.1:9000`, if specified, display media links as https://127.0.0.1:9000/document/$id ; if not, `https://wx.qq.com/cgi-bin/...`
- Groups that should not join automatically. This feature supplements join mode.
  + `--ignore '&fo[o]' '&bar'`, do not auto join channels whose names(generated from Group Name) partially match regex `&fo[o]` or `&bar`
  + `--ignore-display-name 'fo[o]' bar`, short option `-I`, do not auto join channels whose Group Name partially match regex `fo[o]` or `bar`
- `--ignore-brand`, ignore messages from subscription accounts (`MM_USERATTRVERIFYFALG_BIZ_BRAND`)
- IRC related options
  + `--irc-cert cert.pem`, TLS certificate for IRC over TLS. You may concatenate certificate+key, specify a single PEM file and omit `--irc-key`. Use plain IRC if neither --irc-cert nor --irc-key is specified.
  + `--irc-key key.pem`, TLS key for IRC over TLS.
  + `--irc-listen 127.1 ::1`, change IRC listen address to `127.1` and `::1`, overriding `--listen`.
  + `--irc-nicks ray ray1`, reverved nicks for clients. `SpecialUser` will not have these nicks.
  + `--irc-password pass`, set the connection password to `pass`.
  + `--irc-port 6667`, IRC server listen port.
- Join mode, short option `-j`
  + `--join auto`, default: join the channel upon receiving the first message, no rejoin after issuing `/part` and receiving messages later
  + `--join all`: join all the channels
  + `--join manual`: no automatic join
  + `--join new`: like `auto`, but rejoin when new messages arrive even if after `/part`
- `--listen 127.0.0.1`, short option `-l`, change IRC/HTTP/WebSocket listen address to `127.0.0.1`.
- Server side log
  + `--logger-ignore '&test0' '&test1'`, list of ignored regex, do not log contacts/groups whose names partially match
  + `--logger-mask '/tmp/wechat/$channel/%Y-%m-%d.log'`, format of log filenames
  + `--logger-time-format %H:%M`, time format of entries of server side log
- `--paste-wait 0.1`, lines will be hold for up to 0.1 seconds before sending, lines in this interval will be packed to a multiline message
- `--special-channel-prefix`, choices: `&`, `!`, `#`, `##`, prefix for SpecialChannel. [Quassel](quassel-irc.org) does not seem to support channels with prefixes `&`, `--special-channel-prefix '##'` to make Quassel happy

See [wechatircd.service](wechatircd.service) for a template of `/etc/systemd/system/wechatircd.service`.

## Changes in `injector.js`

- Create a WebSocket connection to the server and retry on failures.
- Hook `contactFactory#{addContact,deleteContact}` to watch changes to the contacts.
- `CtrlServer#onmessage`, handle commands (text/file messages, invite someone to the group, ...) from the server.
- `CtrlServer#seenLocalID`, prevent the client from receiving messages sent by itself.

## `wechatircd.py`


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

- Replace the mobile application with your IRC client. See [WeeChat操作各种聊天软件](https://maskray.me/blog/2016-08-13-weechat-rules-all).
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

### Headless browser on Linux

If you cannot tolerant scanning QR codes with your phone everyday, you can run the browser and wechatircd on a server.

- Create a new browser user profile with `chromium --user-data-dir=$HOME/.config/chromium-wechatircd`, and do the aforementioned configuration (certificate for `injector.js`, Tampermonkey, `injector.user.js`), then close the browser.
- Install xvfb (`xorg-server-xvfb` on Arch Linux)
- `xvfb-run -n 99 chromium --user-data-dir=$HOME/.config/chromium-wechatircd https://wx.qq.com`
- Wait a few seconds for the QR code. `DISPLAY=:99 import -window root /tmp/a.jpg && $your_image_viewer /tmp/a.jpg`, take a screenshot and scan the QR code with your mobile application.

You can interact with the browser using VNC:

- `x11vnc -localhost -display :99`
- In another terminal, `vncviewer localhost`

An alternative is x2go, see [无需每日扫码的IRC版微信和QQ：wechatircd、webqqircd](https://maskray.me/blog/2016-07-06-wechatircd-webqqircd-without-scanning-qrcode-daily).

### How are nicks generated?

On the mobile application, users' `On-screen Names` are resolved in this order:
- `Set Remark and Tag` if set
- `My Alias in Group`(`Group Alias`) if set
- `Name` in his/her profile
- `WeChat ID`

Contact information is given in APIs `batchgetcontact` and `webwxsync`. The JSON serialization uses misleading field names.

WeChat friend in `contactFactory#addContact`:

- `.Alias`: `Name` in his/her profile
- `.NickName`: `WeChat ID`
- `.RemarkName`: `Set Remark and Tag`

WeChat friend/non-contact in `.MemberList`:

- `.DisplayName`: `My Alias in Group`
- `.NickName`: `Name` in his/her profile or `WeChat ID`

JSON for one user may be returned repeatedly and all these fields may be empty. Users' nicks are generated by looking for the first non-empty value from these fields: `.RemarkName`, `.NickName`, `.DisplayName`. You may see `xx now known as yy` in your IRC client if a room contact shares multple rooms with you.

## Known issues

### `Uncaught TypeError: angular.extend is not a function`

You may see these messages in the DevTools console:

```
Uncaught TypeError: angular.extend is not a function
    at Object.setUserInfo (index_0c7087d.js:4)
    at index_0c7087d.js:2
    at c (vendor_2de5d3a.js:11)
    at vendor_2de5d3a.js:11
    at c.$eval (vendor_2de5d3a.js:11)
    at c.$digest (vendor_2de5d3a.js:11)
    at c.$apply (vendor_2de5d3a.js:11)
    at l (vendor_2de5d3a.js:11)
    at m (vendor_2de5d3a.js:11)
    at XMLHttpRequest.C.onreadystatechange (vendor_2de5d3a.js:11)
```

```
Uncaught TypeError: angular.forEach is not a function
```

`injector.js` should be executed after `vendor_*.js` and before `index_*.js`. However, TamperMonkey cannot finely control the execution time due to the limitation of Chrome.

### Cannot send/receive new messages when the webpage disconnects from wx.qq.com

The WebSocket connection to `wechatircd.py` should be closed in this case, let users know they should reload the webpage.

### Others

- Log filenames may contain invalid filenames (`:`) on Windows
- Stable channel names. This makes server-side log coherent and users will not be distracted by `PART (Change name)` `JOIN` messages. Channel names are generated from `.NickName` (Group Name) and Group Name may change. I do not know any persistent ID of an account/group because `UserName` changes in each new session.

## References

- [miniircd](https://github.com/jrosdahl/miniircd). Copied a lot of protocol related stuff from miniircd.
- [RFC 2810: Internet Relay Chat: Architecture](https://tools.ietf.org/html/rfc2810)
- [RFC 2811: Internet Relay Chat: Channel Management](https://tools.ietf.org/html/rfc2811)
- [RFC 2812: Internet Relay Chat: Client Protocol](https://tools.ietf.org/html/rfc2812)
- [RFC 2813: Internet Relay Chat: Server Protocol](https://tools.ietf.org/html/rfc2813)
