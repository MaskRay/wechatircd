# wechatircd

网页版微信通过WebSocket把朋友、群信息通知服务端，服务端当IRC server

## 安装

Chrome：安装Switcheroo Redirector扩展，把<https://res.wx.qq.com/zh_CN/htmledition/v2/js/webwxApp2aeaf2.js>重定向至<http://127.1:8000/webwxapp.js>，用一个添加`Access-Control-Allow-Origin: *` header的HTTP server伺服<http://127.1:8000>，也可换成其他host、port。

## 运行

- `./wechatircd.py`启动WebSocket与IRC server
- 访问<https://wx.qq.com>，其中的<https://res.wx.qq.com/zh_CN/htmledition/v2/js/webwxApp2aeaf2.js>已经换成修改版了
- IRC客户端连接127.1:6667，自动加入了`+status` channel，记录32个十六进制数字的token (UUID Version 1)，在网页版微信里对“文件传输助手”(filehelper)或其他人/群(还是不要骚扰别人吧)发这个token
- 在`+status`里有所有微信朋友的nick，nick优先选取备注名(`RemarkName`)，其次为`DisplayName`(原始js根据昵称等自动填写的一个名字)
- 自动加入各微信组

## JS改动

原始文件`orig/webwxApp2aeaf2.js`在Chrome DevTools里格式化后得到`orig/webwxApp2aeaf2.pretty.js`，可以用`diff -u orig/webwxApp2aeaf2.pretty.js webwxapp.js`查看改动。

## 网上搜集的AngularJS控制网页版微信方法

联系人列表
```javascript
angular.element('div[nav-chat-directive]').scope().chatList
```

当前窗口发送消息
```javascript
angular.element('pre:last').scope().editAreaCtn = "Hello，微信";
angular.element('pre:last').scope().sendTextMessage();
```
