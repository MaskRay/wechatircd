# wechatircd

wechatircd injects JavaScript (`injector.js`) to wx.qq.com, which uses WebSocket to communicate with an IRC server (`wechatircd.py`), thus enable IRC clients connected to the server to send and receive messages from WeChat.

## Installation

`>=python-3.5`

`pip install -r requirements.txt`

### Arch Linux

- `yaourt -S wechatircd-git`. It will generate a self-signed key/certificate pair in `/etc/wechatircd/` (see below).
- Import `/etc/wechatircd/cert.pem` to the browser (see below).
- `systemctl start wechatircd`, which runs `/usr/bin/wechatircd --tls-key /etc/wechatircd/key.pem --tls-cert /etc/wechatircd/cert.pem --http-root /usr/share/wechatircd`.

The IRC server listens on 127.0.0.1:6667 (IRC) and 127.0.0.1:9000 (HTTPS + WebSocket over TLS) by default.

### Not Arch Linux

- Generate a self-signed private key/certificate pair with `openssl req -newkey rsa:2048 -nodes -keyout key.pem -x509 -out cert.pem -subj '/CN=127.0.0.1' -dates 9999`.
- Import `cert.pem` to the browser.
- `./wechatircd.py --tls-cert cert.pem --tls-key key.pem`

### Import self-signed certificate to the browser

Chrome/Chromium

- Visit `chrome://settings/certificates`，import `cert.pem`，click the `Authorities` tab，select the `127.0.0.1` certificate, Edit->Trust this certificate for identifying websites.
- Install extension Tampermonkey, install <https://github.com/MaskRay/wechatircd/raw/master/injector.user.js>. It will inject <https://127.0.0.1:9000/injector.js> to <https://wx.qq.com>.

Firefox

- Install extension Greasemonkey，install the user script.
- Visit <https://127.0.0.1:9000/injector.js>, Firefox will show "Your connection is not secure", Advanced->Add Exception->Confirm Security Exception

![](https://maskray.me/static/2016-02-21-wechatircd/run.jpg)

HTTPS、WebSocket over TLS默认用9000端口，使用其他端口需要修改userscript，启动`wechatircd.py`时用`--web-port 10000`指定其他端口。

## Usage

- Run `wechatircd.py` to start the IRC + HTTPS + WebSocket server.
- Visit <https://wx.qq.com>, the injected JavaScript will create a WebSocket connection to the server
- Connect to 127.0.0.1:6667 in your IRC client

You will join `+wechat` channel automatically and find your contact list there. Some commands are available:

- `help`
- `status`, mutual contact list、group/supergroup list

Nicks of contacts are generated from `RemarkName` or `DisplayName`.

## Server options

- Join mode. There are three modes, the default is `--join auto`: join the channel upon receiving the first message. The other two are `--join all`: join all the channels; `--join manual`: no automatic join.
- Groups that should not join automatically. This feature supplement join mode, use `--ignore aa bb` to specify ignored groups by matching generated channel names, `--ignore-topic xx yy` to specify ignored group titles.
- `$nick: ` will be converted to `@$nick ` to notify that user in Telegram. `Client#at_users`
- Surnames come first when displaying Chinese names. `SpecialUser#name`
- History mode. The default is to receive history messages, specify `--history false` to turn off the mode.
- `-l 127.0.0.1`, change IRC listen address to `127.0.0.1`.
- `-p 6667`, change IRC listen port to `6667`.
- `--web-port 9000`, change HTTPS/WebSocket listen port to 9000.
- `--http-root .`, the root directory to serve `app.js`.
- `--tls-key`, TLS key for HTTPS/WebSocket.
- `--tls-cert`, TLS certificate for HTTPS/WebSocket.
- `--logger-ignore '&test0' '&test1'`, list of ignored regex, do not log contacts/groups whose names match
- `--logger-mask '/tmp/wechat/$channel/%Y-%m-%d.log'`, server side log
- `--logger-time-format %H:%M`, time format of server side log

## IRC features

- Standard IRC channels have names beginning with `#`.
- Telegram groups have names beginning with `&`. The channel name is generated from the group title. `SpecialChannel#update`
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
- `/names`, update nicks in the channel.
- `/part $channel`, no longer receive messages from the channel. It just borrows the command `/part` and it will not leave the group.
- `/query $nick`, open a chat window with `$nick`.
- `/summon $nick $message`，add a contact.
- `/topic topic`, change the topic of a group. Because IRC does not support renaming of a channel, you will leave the channel with the old name and join a channel with the new name.
- `/who $channel`, see the member list.

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

## Changes in JavaScript

修改的地方都有`//@`标注，结合diff，方便微信网页版JS更新后重新应用这些修改。增加的代码中大多数地方都用`try catch`保护，出错则`consoleerr(ex.stack)`。原始JS把`console`对象抹掉了……`consoleerr`是我保存的一个副本。

目前的改动如下：

### Beginning of `webwxapp.js`

Create a WebSocket connection to the server and retry on failures.

### Send the contact list to the server periodically

获取所有联系人(朋友、订阅号、群)，`deliveredContact`记录投递到服务端的联系人，`deliveredContact`记录同处一群的非直接联系人。

每隔一段时间把未投递过的联系人发送到服务端。

### 收到微信服务器消息`messageProcess`

原有代码会更新未读标记数及声音提醒，现在改为若成功发送到服务端则不再提醒，以免浏览器的这个标签页造成干扰。

## Python服务端代码

当前只有一个文件`wechatircd.py`，从miniircd抄了很多代码，后来自己又搬了好多RFC上的用不到的东西……

```
.
├── Web                      HTTP(s)/WebSocket server
├── Server                   IRC server
├── Channel
│   ├── StandardChannel      `#`开头的IRC channel
│   ├── StatusChannel        `+wechat`，查看控制当前微信会话
│   └── WeChatRoom           微信群对应的channel，仅该客户端可见
├── (User)
│   ├── Client               IRC客户端连接
│   ├── WeChatUser           微信用户对应的user，仅该客户端可见
├── (IRCCommands)
│   ├── UnregisteredCommands 注册前可用命令：NICK USER QUIT
│   ├── RegisteredCommands   注册后可用命令
```

## IRCv3

支持IRC version 3.1和3.2的`server-time`，`wechatircd.py`传递消息时带上创建时刻，客户端显示消息创建时刻而不是收到消息的时刻。参见<http://ircv3.net/irc/>。IRCv3客户端支持参见<http://ircv3.net/software/clients.html>。

WeeChat配置如下：
```
/set irc.server_default.capabilities "account-notify,away-notify,cap-notify,multi-prefix,server-time,znc.in/server-time-iso,znc.in/self-message"
```

## FAQ

### 用途

可以使用强大的IRC客户端，方便记录日志(微信日志导出太麻烦<https://maskray.me/blog/2014-10-14-wechat-export>)，可以写bot。

## 微信数据获取及控制

少量特殊账户的`UserName`不带`@`前缀：`newsapp,fmessage,filehelper,weibo,qqmail,fmessage`等的；一般账户(公众号、服务号、直接联系人、群友)的`UserName`以`@`开头；微信群的`UserName`以`@@`开头。不同session `UserName`会变化。`Uin`应该是唯一id，但微信网页版API多数时候都返回0，隐藏了真实值。
群的`OwnerUin`字段是群主的`Uin`，但大群用户的`Uin`通常都为0，因此难以对应。

自己的帐号
```javascript
angular.element(document.body).scope().account
```

所有联系人列表
```javascript
angular.element($('#navContact')[0]).scope().allContacts
```

删除群中成员
```javascript
var injector = angular.element(document).injector()
# 这里获取了chatroomFactory，还可用于获取其他factory、service、controller等
var chatroomFactory = injector.get('chatroomFactory')
# 设置其中的`room`与`userToRemove`
chatroomFactory.delMember(room.UserName, userToRemove.UserName)`
```

名称中包含`xxx`的最近联系人列表中的群
```javascript
angular.element($('span:contains("xxx")')).scope().chatContact
```

当前窗口发送消息
```javascript
angular.element('pre:last').scope().editAreaCtn = "Hello，微信";
angular.element('pre:last').scope().sendTextMessage();
```

## 参考

- [miniircd](https://github.com/jrosdahl/miniircd)
- [RFC 2810: Internet Relay Chat: Architecture](https://tools.ietf.org/html/rfc2810)
- [RFC 2811: Internet Relay Chat: Channel Management](https://tools.ietf.org/html/rfc2811)
- [RFC 2812: Internet Relay Chat: Client Protocol](https://tools.ietf.org/html/rfc2812)
- [RFC 2813: Internet Relay Chat: Server Protocol](https://tools.ietf.org/html/rfc2813)
