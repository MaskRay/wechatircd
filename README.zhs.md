# wechatircd

wechatircd类似于bitlbee，在微信网页版和IRC间建起桥梁，可以使用IRC客户端收发微信朋友、群消息、设置群名、邀请删除成员等。

```
           IRC               WebSocket                 HTTPS
IRC client --- wechatircd.py --------- browser         ----- wx.qq.com
                                       injector.user.js
                                       injector.js
```

## 安装

需要Python 3.5或以上，支持`async/await`语法
`pip install -r requirements.txt`安装依赖

### Arch Linux

- `yaourt -S wechatircd-git`。会在`/etc/wechatircd/`下生成自签名证书。
- 把`/etc/wechatircd/cert.pem`导入到浏览器(见下文)
- `systemctl start wechatircd`会运行`/usr/bin/wechatircd --http-cert /etc/wechatircd/cert.pem --http-key /etc/wechatircd/key.pem --http-root /usr/share/wechatircd`

IRC服务器默认监听127.0.0.1:6667 (IRC)和127.0.0.1:9000 (HTTPS + WebSocket over TLS)。

如果你在非本机运行，建议配置IRC over TLS，设置IRC connection password：`/usr/bin/wechatircd --http-cert /etc/wechatircd/cert.pem --http-key /etc/wechatircd/key.pem --http-root /usr/share/wechatircd --irc-cert /path/to/irc.key --irc-key /path/to/irc.cert --irc-password yourpassword`

可以把HTTPS私钥证书用作IRC over TLS私钥证书。使用WeeChat的话，如果觉得让WeeChat信任证书比较麻烦(gnutls会检查hostname)，可以用：
```
set irc.server.wechat.ssl on`
set irc.server.wechat.ssl_verify off
set irc.server.wechat.password yourpassword`
```

### 其他发行版

- `openssl req -newkey rsa:2048 -nodes -keyout key.pem -x509 -out cert.pem -subj '/CN=127.0.0.1' -days 9999`创建密钥与证书。
- 把`cert.pem`导入浏览器，见下文
- `./wechatircd.py --http-cert cert.pem --http-key key.pem`

### 导入自签名证书到浏览器

Chrome/Chromium

- 访问`chrome://settings/certificates`，导入`cert.pem`，在Authorities标签页选择该证书，Edit->Trust this certificate for identifying websites.
- 安装Tampermonkey扩展，点击<https://github.com/MaskRay/wechatircd/raw/master/injector.user.js>安装userscript，效果是在<https://wx.qq.com>页面注入<https://127.0.0.1:9000/injector.js>

Firefox

- 访问<https://127.0.0.1:9000/injector.js>，报告Your connection is not secure，Advanced->Add Exception->Confirm Security Exception
- 安装Greasemonkey扩展，安装userscript

![](https://maskray.me/static/2016-02-21-wechatircd/run.jpg)

HTTPS、WebSocket over TLS默认用9000端口，使用其他端口需要修改userscript，启动`wechatircd.py`时用`--web-port 10000`指定其他端口。

## 使用

- 运行`wechatircd.py`
- 访问<https://wx.qq.com>，userscript注入的JavaScript会向服务器发起WebSocket连接
- IRC客户端连接127.1:6667(weechat的话使用`/server add wechat 127.1/6667`)，会自动加入`+wechat` channel

在`+telegram`发信并不会群发，只是为了方便查看有哪些朋友。
微信朋友的nick优先选取备注名(`RemarkName`)，其次为`DisplayName`(原始JS根据昵称等自动填写的一个名字)

在`+wechat` channel可以执行一些命令：

- `help`，帮助
- `status [pattern]`，已获取的微信朋友、群列表，支持 pattern 参数用来筛选满足 pattern 的结果，目前仅支持子串查询。如要查询所有群，由于群由 `&` 开头，所以可以执行 `status &`。
- `eval $password $expr`: 如果运行时带上了`--password $password`选项，这里可以eval，方便调试，比如`eval $password client.wechat_users`

## 服务器选项

- Join mode. There are three modes, the default is `--join auto`: join the channel upon receiving the first message. The other two are `--join all`: join all the channels; `--join manual`: no automatic join.
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

## IRC命令

- 标准IRC channel名以`#`开头
- WeChat群名以`&`开头。`SpecialChannel#update`
- 联系人带有mode `+v` (voice, 通常显示为前缀`+`)。`SpecialChannel#update_detail`

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

Multi-line messages:

- `!m line0\nline1`
- `!html line0<br>line1`

![](https://maskray.me/static/2016-02-21-wechatircd/topic-kick-invite.jpg)

### 显示

- `MSGTYPE_TEXT`，文本或是视频/语音聊天请求，显示文本
- `MSGTYPE_IMG`，图片，显示`[Image]`跟URL
- `MSGTYPE_VOICE`，语音，显示`[Image]`跟URL
- `MSGTYPE_VIDEO`，视频，显示`[Video]`跟URL
- `MSGTYPE_MICROVIDEO`，微视频?，显示`[MicroVideo]`跟URL
- `MSGTYPE_APP`，订阅号新文章、各种应用分享送红包、URL分享等属于此类，还有子分类`APPMSGTYPE_*`，显示`[App]`跟title跟URL

QQ表情会显示成`<img class="qqemoji qqemoji0" text="[Smile]_web" src="/zh_CN/htmledition/v2/images/spacer.gif">`样，发送时用`[Smile]`即可(相当于在网页版文本输入框插入文本后点击发送)。

Emoji在网页上呈现时为`<img class="emoji emoji1f604" text="_web" src="/zh_CN/htmledition/v2/images/spacer.gif">`，传送至IRC时转换成单个emoji字符。若使用终端IRC客户端，会因为emoji字符宽度为1导致重叠，参见[终端模拟器下使用双倍宽度多色Emoji字体](https://maskray.me/blog/2016-03-13-terminal-emulator-fullwidth-color-emoji)。

## JS改动

修改的地方都有`//@`标注，结合diff，方便微信网页版JS更新后重新应用这些修改。增加的代码中大多数地方都用`try catch`保护，出错则`consoleerr(ex.stack)`。原始JS把`console`对象抹掉了……`consoleerr`是我保存的一个副本。

目前的改动如下：

### `webwxapp.js`开头

创建到服务端的WebSocket连接，若`onerror`则自动重连。监听`onmessage`，收到的消息为服务端发来的控制命令：`send_text_message`、`add_member`等。

### 定期把通讯录发送到服务端

获取所有联系人(朋友、订阅号、群)，`deliveredContact`记录投递到服务端的联系人，`deliveredContact`记录同处一群的非直接联系人。

每隔一段时间把未投递过的联系人发送到服务端。

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

### 使用这个方法的理由

原本想研究微信网页版登录、收发消息的协议，自行实现客户端。参考过<https://github.com/0x5e/wechat-deleted-friends>，仿制了<https://gist.github.com/MaskRay/3b5b3fcbccfcba3b8f29>，可以登录。但根据minify后JS把相关部分重写非常困难，错误处理很麻烦，所以就让网页版JS自己来传递信息。

### 用途

可以使用强大的IRC客户端，方便记录日志(微信日志导出太麻烦<https://maskray.me/blog/2014-10-14-wechat-export>)，可以写bot。

## 我的配置

<https://wiki.archlinux.org/index.php/Systemd/User>

`~/.config/systemd/user/wechatircd.service`:
```
[Unit]
Description=wechatircd
Documentation=https://github.com/MaskRay/wechatircd
After=network.target

[Service]
WorkingDirectory=%h/projects/wechatircd
ExecStart=/home/ray/projects/wechatircd/wechatircd.py --tls-key a.key --tls-cert a.crt --password a --ignore 不想自动加入的群名0 不想自动加入的群名1

[Install]
WantedBy=graphical.target
```

WeeChat:
```
/server add wechat 127.1/6667 -autoconnect
```

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
