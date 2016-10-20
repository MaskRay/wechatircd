# wechatircd

wechatircd类似于bitlbee，在微信网页版和IRC间建起桥梁，可以使用IRC客户端收发微信朋友、群消息、设置群名、邀请删除成员等。

## 原理

访问微信网页版时用userscript `injector.user.js`加载`injector.js`，通过WebSocket与服务端通信。服务端兼做IRC服务器，从而可以让IRC客户端控制网页版。未实现IRC客户端，因此无法把微信群的消息转发到另一个IRC服务器(打通两个群的bot)。

## 安装

需要Python 3.5或以上，支持`async/await`语法
`pip install -r requirements.txt`安装依赖

### Arch Linux

安装<https://aur.archlinux.org/packages/wechatircd-git>，会自动在`/etc/wechatircd/`下生成自签名证书(见下文)，导入浏览器即可。

### 其他发行版

- `openssl req -newkey rsa:2048 -nodes -keyout a.key -x509 -out a.crt -subj '/CN=127.0.0.1' -days 9999`创建密钥与证书。
- 把证书导入浏览器，见下文
- `./wechatircd.py --tls-cert a.crt --tls-key a.key`，会监听127.1:6667的IRC和127.1:9000的HTTPS与WebSocket over TLS

默认监听`127.0.0.1`，如需监听其他地址，可以用选项`-l 127.1 192.168.0.2 192.168.1.2`。

### 浏览器设置

Chrome/Chromium

- 访问`chrome://settings/certificates`，导入a.crt，在Authorities标签页选择该证书，Edit->Trust this certificate for identifying websites.
- 安装Tampermonkey扩展，点击<https://github.com/MaskRay/wechatircd/raw/master/injector.user.js>安装userscript，效果是在<https://wx.qq.com>页面注入<https://127.0.0.1:9000/injector.js>

Firefox

- 访问<https://127.0.0.1:9000/injector.js>，报告Your connection is not secure，Advanced->Add Exception->Confirm Security Exception
- 安装Greasemonkey扩展，安装userscript

![](https://maskray.me/static/2016-02-21-wechatircd/run.jpg)

HTTPS、WebSocket over TLS默认用9000端口，使用其他端口需要修改userscript，启动`wechatircd.py`时用`--web-port 10000`指定其他端口。

### 无TLS(不推荐)

如果嫌X.509太麻烦的话可以不用TLS，但浏览器可能会在console里给出警告甚至拒绝。

- 执行`./wechatircd.py`，会监听127.1:6667的IRC和127.1:9000的HTTP与WebSocket，HTTP用于伺服项目根目录下的`injector.js`。
- 安装userscript

## 使用

- 登录<https://wx.qq.com>，会自动发起WebSocket连接。若打开多个，只有第一个生效
- IRC客户端连接127.1:6667(weechat的话使用`/server add wechat 127.1/6667`)，会自动加入`+wechat` channel

在`+telegram`发信并不会群发，只是为了方便查看有哪些朋友。
微信朋友的nick优先选取备注名(`RemarkName`)，其次为`DisplayName`(原始JS根据昵称等自动填写的一个名字)

在`+wechat` channel可以执行一些命令：

- `help`，帮助
- `status [pattern]`，已获取的微信朋友、群列表，支持 pattern 参数用来筛选满足 pattern 的结果，目前仅支持子串查询。如要查询所有群，由于群由 `&` 开头，所以可以执行 `status &`。
- `eval $password $expr`: 如果运行时带上了`--password $password`选项，这里可以eval，方便调试，比如`eval $password client.wechat_users`

## IRC命令

wechatircd是个简单的IRC服务器，可以执行通常的IRC命令，可以对其他客户端私聊，创建standard channel(以`#`开头的channel)。另外若与微信网页版连接，就能看到微信联系人(朋友、群联系人)显示为特殊nick、微信群显示为特殊channel(以`&`开头，根据群名自动设置名称)

这些特殊nick与channel只有当前客户端能看到，因此一个服务端支持多个微信帐号同时登录，每个用不同的IRC客户端控制。另外，以下命令会有特殊作用：

- 程序默认选项为`--join auto`，收到某个微信群的第一条消息后会自动加入对应的channel，即开始接收该微信群的消息。
- `/dcc send nick/channel filename`，给微信朋友或微信群发图片/文件。参见<https://en.wikipedia.org/wiki/Direct_Client-to-Client#DCC_SEND>
- `/invite nick [channel]`为邀请微信朋友加入群
- `/join [channel]`表示开始接收该微信群的消息
- `/kick nick`，删除群成员。因为网页版数据限制，无法立即获悉成员变动，channel里可能看不到改变，但实际已经生效了
- `/list`，列出所有微信群
- `/names`，更新当前群成员列表
- `/part [channel]`的IRC原义为离开channel，转换为微信代表在当前IRC会话中不再接收该微信群的消息。不用担心，wechatircd并没有主动退出群的功能
- `/query nick`打开与`$nick`的私聊窗口，与之私聊即为在微信上和他/她/它对话
- `/summon nick message`，发送添加朋友请求，message为验证信息
- `/topic topic`为重命名群，因为IRC不支持channel改名，实现方式为会自动退出原名称的channel并加入新名称的channel
- `/who channel`，查看群成员列表

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
