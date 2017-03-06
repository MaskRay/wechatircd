# wechatircd [![IRC](https://img.shields.io/badge/IRC-freenode-yellow.svg)](https://webchat.freenode.net/?channels=wechatircd) [![Telegram](https://img.shields.io/badge/chat-Telegram-blue.svg)](https://t.me/wechatircd) [![Gitter](https://img.shields.io/badge/chat-Gitter-753a88.svg)](https://gitter.im/wechatircd/wechatircd)

wechatircd在wx.qq.com里注入JavaScript，用WebSocket与IRC server(`wechatircd.py`)通信，使得IRC客户端可以收发微信朋友、群消息、设置群名、邀请删除成员等。

```
           IRC               WebSocket                 HTTPS
IRC client --- wechatircd.py --------- browser         ----- wx.qq.com
                                       injector.user.js
                                       injector.js
```

加入freenode的#wechatircd频道，或[Telegram group](https://t.me/wechatircd)。

### Arch Linux

- `yaourt -S wechatircd-git`。会在`/etc/wechatircd/`下生成自签名证书。
- 把`/etc/wechatircd/cert.pem`导入到浏览器(见下文)
- `systemctl start wechatircd`会运行`/usr/bin/wechatircd --http-cert /etc/wechatircd/cert.pem --http-key /etc/wechatircd/key.pem --http-root /usr/share/wechatircd`

IRC服务器默认监听127.0.0.1:6667 (IRC)和127.0.0.1:9000 (HTTPS + WebSocket over TLS)。

如果你在非本机运行，建议配置IRC over TLS，设置IRC connection password，添加这些选项：`--irc-cert /path/to/irc.key --irc-key /path/to/irc.cert --irc-password yourpassword`。

可以把HTTPS私钥证书用作IRC over TLS私钥证书。使用WeeChat的话，如果觉得让WeeChat信任证书比较麻烦(gnutls会检查hostname)，可以用：
```
set irc.server.wechat.ssl on
set irc.server.wechat.ssl_verify off
set irc.server.wechat.password yourpassword
```

### 其他发行版

- python >= 3.5
- `pip install -r requirements.txt`
- `openssl req -newkey rsa:2048 -nodes -keyout key.pem -x509 -out cert.pem -subj '/CN=127.0.0.1' -days 9999`创建密钥与证书。
- 把`cert.pem`导入浏览器，见下文
- `./wechatircd.py --http-cert cert.pem --http-key key.pem`

### Userscript和自签名证书

Chrome/Chromium

- 访问`chrome://settings/certificates`，导入`cert.pem`，在Authorities标签页选择该证书，Edit->Trust this certificate for identifying websites.
- 安装Tampermonkey扩展，点击<https://github.com/MaskRay/wechatircd/raw/master/injector.user.js>安装userscript，效果是在<https://wx.qq.com>页面注入<https://127.0.0.1:9000/injector.js>

Firefox

- 访问<https://127.0.0.1:9000/injector.js>，报告Your connection is not secure，Advanced->Add Exception->Confirm Security Exception
- 安装Greasemonkey扩展，安装userscript

![](https://maskray.me/static/2016-02-21-wechatircd/meow.jpg)

HTTPS、WebSocket over TLS默认用9000端口，使用其他端口需要修改userscript，启动`wechatircd.py`时用`--web-port 10000`指定其他端口。

## 使用

- 运行`wechatircd.py`
- 访问<https://wx.qq.com>，userscript注入的JavaScript会向服务器发起WebSocket连接
- IRC客户端连接127.1:6667(weechat的话使用`/server add wechat 127.1/6667`)，会自动加入`+wechat` channel

在`+wechat`发信并不会群发，只是为了方便查看有哪些朋友。在`+wechat` channel可以执行一些命令：

- `help`，帮助
- `eval $expr`: 比如`eval server.nick2special_user` `eval server.name2special_room`
- `status [pattern]`，已获取的微信朋友、群列表，支持 pattern 参数用来筛选满足 pattern 的结果，目前仅支持子串查询。如要查询所有群，由于群由 `&` 开头，所以可以执行 `status &`。
- `reload_contact __all__`，遇到`no nuch nick/channel`消息时可用，会重新加载所有联系人信息

服务器只能和一个帐号绑定，但支持多个IRC客户端。

## IRC功能

- 标准IRC channel名以`#`开头
- WeChat群名以`&`开头。`SpecialChannel#update`
- 联系人带有mode `+v` (voice, 通常显示为前缀`+`)。`SpecialChannel#update_detail`
- 多行消息：`!m line0\nline1`
- 多行消息：`!html line0<br>line1`
- `nick0: nick1: test`会被转换成`@GroupAlias0 @GroupAlias1 test`，`GroupAlias0` 是那个用户自己设置的名字，不是你设置的`Set Remark and Tag`，对应移动端的`On-screen names`
- 回复12:34:SS的消息：`@1234 !m multi\nline\nreply`，会发送`「Re GroupAlias: text」text`
- 回复12:34:56的消息：`!m @123456 multi\nline\nreply`
- 回复朋友/群的倒数第二条消息(自己的消息不计数)：`@2 reply`
- 粘贴检测。待发送消息延迟0.1秒发送，期间收到的所有行合并为一个多行消息发送

`!m `, `@3 `, `nick: `可以任意安排顺序。

对于WeeChat，默认的anti-flood机制会让发出去的两条消息间隔至少2秒。禁用该机制使粘贴检测生效：
```
/set irc.server.wechat.anti_flood_prio_high 0
```

若客户端启用IRC 3.1 3.2的`server-time`扩展，`wechatircd.py`会在发送的消息中包含 网页版获取的时间戳。客户端显示消息时时间就会和服务器收到的消息的时刻一致。参见<http://ircv3.net/irc/>。参见<http://ircv3.net/software/clients.html>查看IRCv3的客户端支持情况。

WeeChat配置方式：
```
/set irc.server_default.capabilities "account-notify,away-notify,cap-notify,multi-prefix,server-time,znc.in/server-time-iso,znc.in/self-message"
```

支持的IRC命令：

- `/cap`，列出支持的capabilities
- `/dcc send $nick/$channel $filename`, 发送图片或文件。借用了IRC客户端的`/dcc send`命令，但含义不同，参见<https://en.wikipedia.org/wiki/Direct_Client-to-Client#DCC_SEND>
- `/invite $nick [$channel]`，邀请用户加入群
- `/kick $nick`，删除群成员，群主才有效。由于网页版限制，可能收不到群成员变更的消息
- `/kill $nick [$reason]`，断开指定客户端的连接
- `/list`，列出所有群
- `/mode +m`, `--join new`模式下防止自动重新join。用`/mode -m`撤销
- `/motd`，查看本repo最近5个commits
- `/names`, 更新当前群成员列表
- `/part [$channel]`的IRC原义为离开channel，这里表示当前IRC会话中不再接收该群的消息。不用担心，telegramircd并没有主动退出群的功能
- `/query $nick`，打开和`$nick`聊天的窗口
- `/squit $any`，log out
- `/summon $nick $message`，发送添加朋友请求，`$message`为备注消息
- `/topic topic`修改群标题。因为IRC不支持channel改名，实现为离开原channel并加入新channel
- `/who $channel`，查看群的成员列表

![](https://maskray.me/static/2016-02-21-wechatircd/demo.jpg)

### 显示

- `MSGTYPE_TEXT`，文本或是视频/语音聊天请求，显示文本
- `MSGTYPE_IMG`，图片，显示`[Image]`跟URL
- `MSGTYPE_VOICE`，语音，显示`[Image]`跟URL
- `MSGTYPE_VIDEO`，视频，显示`[Video]`跟URL
- `MSGTYPE_MICROVIDEO`，微视频?，显示`[MicroVideo]`跟URL
- `MSGTYPE_APP`，订阅号新文章、各种应用分享送红包、URL分享等属于此类，还有子分类`APPMSGTYPE_*`，显示`[App]`跟title跟URL

QQ表情会显示成`<img class="qqemoji qqemoji0" text="[Smile]_web" src="/zh_CN/htmledition/v2/images/spacer.gif">`样，发送时用`[Smile]`即可(相当于在网页版文本输入框插入文本后点击发送)。

Emoji在网页上呈现时为`<img class="emoji emoji1f604" text="_web" src="/zh_CN/htmledition/v2/images/spacer.gif">`，传送至IRC时转换成单个emoji字符。若使用终端IRC客户端，会因为emoji字符宽度为1导致重叠，参见[终端模拟器下使用双倍宽度多色Emoji字体](https://maskray.me/blog/2016-03-13-terminal-emulator-fullwidth-color-emoji)。

## 服务器选项

- `--config`, short option `-c`，配置文件路径，参见[config](config)
- HTTP/WebSocket相关选项
  + `--http-cert cert.pem`，HTTPS/WebSocketTLS的证书。你可以把证书和私钥合并为一个文件，省略`--http-key`选项。如果`--http-cert`和`--http-key`均未指定，使用不加密的HTTP
  + `--http-key key.pem`，HTTPS/WebSocket的私钥
  + `--http-listen 127.1 ::1`，HTTPS/WebSocket监听地址设置为`127.1`和`::1`，overriding `--listen`
  + `--http-port 9000`，HTTPS/WebSocket监听端口设置为9000
  + `--http-root .`, 存放`injector.js`的根目录
- 指定不自动加入的群名，用于补充join mode
  + `--ignore 'fo[o]' bar`，channel名部分匹配正则表达式`fo[o]`或`bar`
  + `--ignore-topic 'fo[o]' bar`, 群标题部分匹配正则表达式`fo[o]`或`bar`
- `--ignore-brand`，忽略来自订阅号的消息(`MM_USERATTRVERIFYFALG_BIZ_BRAND`)
- IRC相关选项
  + `--irc-cert cert.pem`，IRC over TLS的证书。你可以把证书和私钥合并为一个文件，省略`--irc-key`选项。如果`--irc-cert`和`--irc-key`均未指定，使用不加密的IRC
  + `--irc-key key.pem`，IRC over TLS的私钥
  + `--irc-listen 127.1 ::1`，IRC over TLS监听地址设置为`127.1`和`::1`，overriding `--listen`
  + `--irc-nicks ray ray1`，给客户端保留的nick。`SpecialUser`不会占用这些名字
  + `--irc-password pass`，IRC connection password设置为`pass`
  + `--irc-port 6667`，IRC监听端口
- Join mode，短选项`-j`
  + `--join auto`，默认：收到某个群第一条消息后自动加入，如果执行过`/part`命令了，则之后收到消息不会重新加入
  + `--join all`：加入所有channel
  + `--join manual`：不自动加入
  + `--join new`：类似于`auto`，但执行`/part`命令后，之后收到消息仍自动加入
- `--listen 127.0.0.1`，`-l`，IRC/HTTP/WebSocket监听地址设置为`127.0.0.1`
- 服务端日志
  + `--logger-ignore '&test0' '&test1'`，不记录部分匹配指定正则表达式的朋友/群日志
  + `--logger-mask '/tmp/wechat/$channel/%Y-%m-%d.log'`，日志文件名格式
  + `--logger-time-format %H:%M`，日志单条消息的时间格式
- `--paste-wait`，待发送消息延迟0.1秒发送，期间收到的所有行合并为一个多行消息发送

[wechatircd.service](wechatircd.service)是`/etc/systemd/system/wechatircd.service`的模板，修改其中的`User=` and `Group=`。

## JS改动

- 创建到服务端的WebSocket连接，自动重连
- Hook `contactFactory#{addContact,deleteContact}`记录联系人列表的变更
- `CtrlServer#onmessage`，处理服务端的控制命令
- `CtrlServer#seenLocalID`，防止客户端收到自己发送的消息

## `wechatircd.py`

```
.
├── Web                      HTTP(s)/WebSocket server
├── Server                   IRC server
├── Channel
│   ├── StandardChannel      `#`开头的IRC channel
│   ├── StatusChannel        `+wechat`，查看控制当前微信会话
│   └── SpecialChannel       微信群对应的channel，仅该客户端可见
├── (User)
│   ├── Client               IRC客户端连接
│   ├── SpecialUser          微信用户对应的user，仅该客户端可见
├── (IRCCommands)
│   ├── UnregisteredCommands 注册前可用命令：NICK USER QUIT
│   ├── RegisteredCommands   注册后可用命令
```

## FAQ

### 动机

- 用IRC客户端代替移动端应用。参见[WeeChat操作各种聊天软件](https://maskray.me/blog/2016-08-13-weechat-rules-all).
- Bot
- 方便记录日志(微信日志导出太麻烦<https://maskray.me/blog/2014-10-14-wechat-export>)

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

### Linux下headless浏览器

如果不能忍受每日扫码，可以在服务器上运行浏览器和wechatircd。

- 创建一个新Chromium profile：`chromium --user-data-dir=$HOME/.config/chromium-wechatircd`，配置浏览器(`injector.js`用的证书, Tampermonkey, `injector.user.js`)，关闭浏览器
- 安装xvfb (Arch Linux里叫`xorg-server-xvfb`)
- `xvfb-run -n 99 chromium --user-data-dir=$HOME/.config/chromium-wechatircd https://wx.qq.com`
- 等数秒待QR码加载。`DISPLAY=:99 import -window root /tmp/a.jpg && $your_image_viewer /tmp/a.jpg`，截图后用移动端应用扫码

可以用VNC与浏览器交互：

- `x11vnc -localhost -display :99`
- 在另一个终端`vncviewer localhost`

另一种方案是x2go，参见[无需每日扫码的IRC版微信和QQ：wechatircd、webqqircd](https://maskray.me/blog/2016-07-06-wechatircd-webqqircd-without-scanning-qrcode-daily)。

### Nick如何生成？

移动端应用中，用户`显示群成员昵称`(`On-screen Names`)按如下顺序：
- `设置备注和标签`(`Set Remark and Tag`)，如果设置过
- `群昵称`(`My Alias in Group`, `Group Alias`)，如果设置过
- Profile里性别标志旁的名字
- `微信号`(`WeChat ID`)

`batchgetcontact`和`webwxsync`等API提供的JSON使用了让人容易误解的字段名：

`contactFactory#addContact`里的朋友：

- `.Alias`: profile里的名字
- `.NickName`: `WeChat ID`
- `.RemarkName`: `Set Remark and Tag`

`.MemberList`里的朋友/群友

- `.DisplayName`: `My Alias in Group`
- `.NickName`: profile里的名字，或`WeChat ID`

一个用户的JSON可能被返回多次，上述字段都可能为空。用户的nick按照如下顺序查找第一个非空域：`.RemarkName`, `.NickName`, `.DisplayName`。如果一个群友和你在多个群里，你可能会在IRC客户端里看到`xx now known as yy`。

## 已知问题

DevTools console里可能有如下消息：

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

原因是`injector.js`得在`vendor_*.js`后`index_*.js`前执行。但TamperMonkey无法精细控制script的运行时机。

### 网页与wx.qq.com断开连接后无法收发消息

在这种情况下，网页与`wechatircd.py`的WebSocket连接应该断开，让用户知道他们需要刷新页面。

## 参考

- [miniircd](https://github.com/jrosdahl/miniircd)，抄了很多IRC协议相关代码
- [RFC 2810: Internet Relay Chat: Architecture](https://tools.ietf.org/html/rfc2810)
- [RFC 2811: Internet Relay Chat: Channel Management](https://tools.ietf.org/html/rfc2811)
- [RFC 2812: Internet Relay Chat: Client Protocol](https://tools.ietf.org/html/rfc2812)
- [RFC 2813: Internet Relay Chat: Server Protocol](https://tools.ietf.org/html/rfc2813)
