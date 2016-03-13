# wechatircd

wechatircd类似于bitlbee，在微信网页版和IRC间建起桥梁，可以使用IRC客户端收发微信朋友、群消息、设置群名、邀请删除成员等。

## 原理

修改微信网页版用的JS，通过WebSocket把信息发送到服务端，服务端兼做IRC服务端，把IRC客户端的命令通过WebSocket传送到网页版JS执行。

## 安装

需要Python 3.5或以上，支持`async/await`语法
`pip install -r requirements.txt`安装依赖

## 运行

### HTTPS、WebSocket over TLS

推荐使用TLS。

- `openssl req -newkey rsa:2048 -nodes -keyout a.key -x509 -out a.crt -subj '/CN=127.0.0.1'`创建密钥与证书。
- Chrome访问`chrome://settings/certificates`，导入a.crt，在Authorities标签页选择该证书，Edit->Trust this certificate for identifying websites.
- Chrome安装Switcheroo Redirector扩展，把<https://res.wx.qq.com/zh_CN/htmledition/v2/js/webwxApp2c32b4.js>重定向至<https://127.0.0.1:9000/webwxapp.js>。若js更新，该路径会变化。
- `./wechatircd.py --tls-cert a.crt --tls-key a.key`，会监听127.1:6667的IRC和127.1:9000的HTTPS与WebSocket over TLS

![](https://maskray.me/static/2016-02-21-wechatircd/run.jpg)

### HTTP、WebSocket

如果嫌X.509太麻烦的话可以不用TLS，但Chrome会在console里给出警告。

- 执行`./wechatircd.py`，会监听127.1:6667的IRC和127.1:9000的HTTP与WebSocket，HTTP用于伺服项目根目录下的`webwxapp.js`。
- 把<https://res.wx.qq.com/zh_CN/htmledition/v2/js/webwxApp2c32b4.js>重定向至<http://127.0.0.1:9000/webwxapp.js>。若js更新，该路径会变化。
- 把`webwxapp.js`中`var ws = new MyWebSocket('wss://127.0.0.1:9000')`修改成`ws://127.0.0.1:9000`

### IRC客户端

- IRC客户端连接127.1:6667，会自动加入`+status` channel，并给出UUID Version 1的token
- 登录<https://wx.qq.com>，对“文件传输助手”(filehelper)或其他人/群(还是不要骚扰别人吧)发这个token
- 回到IRC客户端，可以看到微信朋友加入了`+status` channel，在这个channel发信并不会群发，只是为了方便查看有哪些朋友。
- 微信朋友的nick优先选取备注名(`RemarkName`)，其次为`DisplayName`(原始JS根据昵称等自动填写的一个名字)

在`+status` channel可以执行一些命令：

- `help`，帮助
- `status`，已获取的微信朋友、群列表
- `eval $password $expr`: 如果运行时带上了`--password $password`选项，这里可以eval，方便调试，比如`eval $password client.wechat_users`


如果微信网页版显示QR code要求重新登录，登录后继续对“文件传输助手”32个十六进制数字的token即可。
服务端或客户端重启，根据`+status` channel上新的token(或者在`+status` channel发送`new`消息重新获取一个)，在微信网页版上对“文件传输助手”输入token。

## IRC命令

wechatircd是个简单的IRC服务器，可以执行通常的IRC命令，可以对其他客户端私聊，创建standard channel(以`#`开头的channel)。另外若用token与某个微信网页版连接的，就能看到微信联系人(朋友、群联系人)显示为特殊nick、微信群显示为特殊channel(以`&`开头，根据群名自动设置名称)

这些特殊nick与channel只有当前客户端能看到，因此一个服务端支持多个微信帐号同时登录，每个用不同的IRC客户端控制。另外，以下命令会有特殊作用：

- `/query nick`打开与`$nick`的私聊窗口，与之私聊即为在微信上和他/她/它对话
- `/list`列出所有微信群
- 程序默认选项为`--join auto`，收到某个微信群的第一条消息后会自动加入对应的channel，即开始接收该微信群的消息。`/part [channel]`的IRC原义为离开channel，转换为微信代表在当前IRC会话中不再接收该微信群的消息。不用担心，wechatircd并没有主动退出群的功能
- `/join [chatroom]`表示继续接收该微信群的消息
- `/invite nick [channel]`为邀请微信朋友加入群
- 在微信群的channel里`/kick nick`即为删除成员。因为网页版数据限制，无法立即获悉成员变动，channel里可能看不到改变，但实际已经生效了
- `/topic topic`为重命名群，因为IRC不支持channel改名，实现方式为会自动退出原名称的channel并加入新名称的channel

![](https://maskray.me/static/2016-02-21-wechatircd/topic-kick-invite.jpg)

### 显示

- `MSGTYPE_TEXT`，文本或是视频/语音聊天请求，显示文本
- `MSGTYPE_IMG`，图片，显示`[Image]`跟URL
- `MSGTYPE_VOICE`，语音，显示`[Image]`跟URL
- `MSGTYPE_VIDEO`，视频，显示`[Video]`跟URL
- `MSGTYPE_MICROVIDEO`，微视频?，显示`[MicroVideo]`跟URL
- `MSGTYPE_APP`，订阅号新文章、各种应用分享送红包、URL分享等属于此类，还有子分类`APPMSGTYPE_*`，显示`[App]`跟title跟URL

Emoji会显示成`<img class="qqemoji qqemoji0" text="[Smile]_web" src="/zh_CN/htmledition/v2/images/spacer.gif">`样，发送时用`[Smile]`即可(相当于在网页版文本输入框插入文本后点击发送)

## JS改动

原始文件`orig/webwxApp*.js`在Chrome DevTools里格式化后得到`orig/webwxApp*.pretty.js`，可以用`diff -u orig/webwxApp*.pretty.js webwxapp.js`查看改动。

修改的地方都有`//@`标注，结合diff，方便微信网页版JS更新后重新应用这些修改。增加的代码中大多数地方都用`try catch`保护，出错则`consoleerr(ex.stack)`。原始JS把`console`对象抹掉了……`consoleerr`是我保存的一个副本。

目前的改动如下：

### `webwxapp.js`开头

创建到服务端的WebSocket连接，若`onerror`则自动重连。监听`onmessage`，收到的消息为服务端发来的控制命令：`send_text_message`、`add_member`等。

### 检测输入串是否为32个字符的十六进制数UUID version 1

对“文件传输助手”或其他人发送消息后判断是否为32个字符的十六进制数UUID version 1，是则设置全局变量`token`。

### 定期把通讯录发送到服务端

获取所有联系人(朋友、订阅号、群)，`deliveredContact`记录投递到服务端的联系人，`deliveredContact`记录同处一群的非直接联系人。

每隔一段时间把未投递过的联系人发送到服务端。如果token发生变化，就会清空`deliveredContact`等。若联系人信息发生变化，也会更新。

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
│   ├── StatusChannel        `+status`，查看控制当前微信会话
│   └── WeChatRoom           微信群对应的channel，仅该客户端可见
├── (User)
│   ├── Client               IRC客户端连接
│   ├── WeChatUser           微信用户对应的user，仅该客户端可见
├── (IRCCommands)
│   ├── UnregisteredCommands 注册前可用命令：NICK USER QUIT
│   ├── RegisteredCommands   注册后可用命令
```

## FAQ

### 使用这个方法的理由

原本想研究微信网页版登录、收发消息的协议，自行实现客户端。参考过<https://github.com/0x5e/wechat-deleted-friends>，仿制了<https://gist.github.com/MaskRay/3b5b3fcbccfcba3b8f29>，可以登录。但根据minify后JS把相关部分重写非常困难，错误处理很麻烦，所以就让网页版JS自己来传递信息。

### 为什么用扩展实现JS重定向？

微信网页版使用AngularJS，不知道如何优雅地monkey patch AngularJS……一旦原JS执行了，bootstrap了整个页面，我不知道如何用后执行的`<script>`修改它的行为。

因此原来打算用UserScript阻止该`<script>`标签的执行，三个时机里`@run-at document-begin`看不到`<body>`；`document-body`时`<body>`可能只部分加载了，旧`<script>`标签已经在加载过程中，添加修改后的`<script>`没法保证在旧`<script>`前执行；`@run-at document-end`则完全迟了。

另外可以在`@run-at document-begin`时`window.stop()`阻断页面加载，然后换血，替换整个`document.documentElement`，先加载自己的小段JS，再加载<https://res.wx.qq.com/zh_CN/htmledition/v2/js/{libs*,webwxApp*}.js>，详见<http://stackoverflow.com/questions/11638509/chrome-extension-remove-script-tags>。我不知道如何控制顺序。另外，两个原有JS的HTTP回应中`Access-Control-Allow-Origin: wx.qq.com`格式不对，浏览器会拒绝XMLHttpRequest加载。

Firefox支持beforescriptexecute事件，可以用UserScript实现劫持、更换`<script>`。

### 用途

可以使用强大的IRC客户端，方便记录日志(微信日志导出太麻烦<https://maskray.me/blog/2014-10-14-wechat-export>)，可以写bot。

### 查看微信网页版当前采用的token

DevTools console里查看`token`变量

## 我的配置

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
