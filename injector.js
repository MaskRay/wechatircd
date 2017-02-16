'use strict'
const Common = {
  EMOJI_MAXIUM_SIZE: 120,
  WEBSOCKET_URL: 'wss://127.0.0.1:9000/ws',
  DEBUG: false,
  SEND_TEXT_MESSAGE_TIMEOUT: 10,
}

const console2 = {
  log: console.log,
  error: console.error,
}

class CtrlServer {
  constructor() {
    const eventTarget = document.createElement('div')
    eventTarget.addEventListener('open', data => this.reset())
    eventTarget.addEventListener('message', data => this.onmessage && this.onmessage(data))
    this.dispatch = eventTarget.dispatchEvent.bind(eventTarget)
    this.ws = null
    this.forcedClose = false
    this.open(false)
    setInterval(() => this.sync_contacts(), 5000)

    this.localID = null // 服务端通过WebSocket控制网页版发送消息时指定LocalID，区分网页版上发送的消息(需要投递到服务端)与服务端发送的消息(不需要投递)
    this.seenLocalID = new Set() // 记录服务端请求发送的消息的LocalID，避免服务端收到自己发送的消息
    this.contacts = new Map
    this.reset()
  }

  close() {
    this.forcedClose = true
    if (this.ws)
      this.ws.close()
  }

  onmessage(data) {
    try {
      data = JSON.parse(data.detail)
      switch (data.command) {
      case 'close':
        this.close()
        this.open(false)
        break
      case 'add_friend':
        $.ajax({
          method: 'POST',
          url: confFactory.API_webwxverifyuser+'?r='+utilFactory.now(),
          dataType: 'json',
          contentType: 'application/json',
          data: JSON.stringify(angular.extend(accountFactory.getBaseRequest(), {
            Opcode: confFactory.VERIFYUSER_OPCODE_SENDREQUEST,
            VerifyUserListSize: 1,
            VerifyUserList: [{
              Value: data.user,
              VerifyUserTicket: ""
            }],
            VerifyContent: data.message,
            SceneListCount: 1,
            SceneList: [confFactory.ADDSCENE_PF_WEB],
            skey: accountFactory.getSkey()
          }))
        }).done(() => {
          console2.log('+ add_friend_ack')
          this.send({command: 'add_friend_ack', user: data.user})
        }).fail(() => {
          console2.error('- add_friend_nak')
          this.send({command: 'add_friend_nak', user: data.user})
        })
        break
      case 'send_file':
        let uploadmediarequest = JSON.stringify(Object.assign({}, accountFactory.getBaseRequest(), {
          ClientMediaId: utilFactory.now(),
          TotalLen: data.body.length,
          StartPos: 0,
          DataLen: data.body.length,
          MediaType: confFactory.UPLOAD_MEDIA_TYPE_ATTACHMENT,
        }))
        let mime = 'application/octet-stream'
        if (data.filename.endsWith('.bmp'))
          mime = 'image/bmp'
        else if (data.filename.endsWith('.gif'))
          mime = 'image/gif'
        else if (data.filename.endsWith('.png'))
          mime = 'image/png'
        else if (/\.jpe?g/.test(data.filename))
          mime = 'image/jpeg'
        let is_image = /^image/.test(mime)
        let body = new Uint8Array(data.body.length)
        for (let i = 0; i < data.body.length; i++)
          body[i] = data.body.charCodeAt(i)
        let fields = {
          id: 'WU_FILE_0',
          name: data.filename,
          type: mime,
          lastModifiedDate: ''+new Date,
          size: data.body.length,
          mediatype: (is_image ? 'pic' : 'doc'),
          uploadmediarequest,
          webwx_data_ticket: utilFactory.getCookie('webwx_data_ticket'),
          pass_ticket: accountFactory.getPassticket(),
        }
        let fd = new FormData
        for (let i in fields)
          fd.append(i, fields[i])
        fd.append('filename', new Blob([body], {type: mime}), data.filename)
        $.ajax({
          method: 'POST',
          url: confFactory.API_webwxuploadmedia+'?f=json',
          processData: false,
          contentType: false,
          data: fd,
        }).done((res) => {
          res = JSON.parse(res)
          if (res.BaseResponse.Ret === 0 && res.MediaId) {
            console2.log('+ API_webwxuploadmedia done')
            let ext = data.filename.match(/\.(\w+)$/)
            ext = ext ? ext[1] : ''
            let old = chatFactory.getCurrentUserName()
            try {
              chatFactory.setCurrentUserName(data.receiver)
              let m = chatFactory.createMessage({
                MsgType: is_image ? confFactory.MSGTYPE_IMAGE : confFactory.MSGTYPE_APP,
                MediaId: res.MediaId,
                FileName: data.filename,
                FileSize: body.length,
                MMFileId: 'WU_FILE_0',
                MMFileExt: ext,
                MMUploadProgress: 100,
                MMFileStatus: confFactory.MM_SEND_FILE_STATUS_SUCCESS,
              })
              chatFactory.appendMessage(m)
              chatFactory.sendMessage(m)
            } finally {
              chatFactory.setCurrentUserName(old)
            }
          } else
            this.send({command: 'send_file_message_nak',
                receiver: data.receiver,
                filename: data.filename})
        }).fail(() => {
          this.send({command: 'send_file_message_nak',
              receiver: data.receiver,
              filename: data.filename})
        })
        break
      case 'send_text_message':
        let old = chatFactory.getCurrentUserName()
        try {
          chatFactory.setCurrentUserName(data.receiver)
          let localID = this.localID = (utilFactory.now() + Math.random().toFixed(3)).replace(".", "")
          this.seenLocalID.add(localID)
          if (data.message.startsWith('!html '))
            data.message = data.message.substr(6)
          else if (data.message.startsWith('!m '))
            data.message = data.message.substr(3).replace(/\\n/g, '\n').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
          else
            data.message = data.message.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
          editArea.editAreaCtn = data.message
          editArea.sendTextMessage()
          setTimeout(() => {
            if (this.seenLocalID.has(localID))
              this.send({command: 'send_text_message_nak',
                receiver: data.receiver,
                message: data.message
              })
          }, Common.SEND_TEXT_MESSAGE_TIMEOUT)
        } catch (ex) {
          this.send({command: 'web_debug', message: 'send text message exception: '  + ex.message + "\nstack: " + ex.stack})
          console2.error(ex.stack)
        } finally {
          this.localID = null
          chatFactory.setCurrentUserName(old)
        }
        break
      case 'add_member':
        chatroomFactory.addMember(data.room, data.user)
        break
      case 'del_member':
        chatroomFactory.delMember(data.room, data.user)
        break
      case 'eval':
        this.send({command: 'web_debug', input: data.expr, result: eval('(' + data.expr + ')')})
        break
      case 'mod_topic':
        chatroomFactory.modTopic(data.room, data.topic)
        break
      case 'reload_contact':
        if (data.name === '__all__')
          this.pending_contacts = new Set(this.contacts.keys())
        else if (data.name)
          for (let [username, user] of Object.entries(contactFactory.getAllContacts())) {
            if (user.RemarkName === data.name || user.getDisplayName() === data.name) {
              this.pending_contacts.add(username)
              this.send({command: 'web_debug', reloaded_contact: user})
            }
          }
        break
      }
    } catch (ex) {
      this.send({command: 'web_debug', message: 'handle message exception: '  + ex.message + "\nstack: " + ex.stack})
      console2.error(ex.stack)
    }
  }

  open(reconnect) {
    this.ws = new WebSocket(Common.WEBSOCKET_URL)

    function newEvent(s, data) {
      let e = document.createEvent('CustomEvent')
      e.initCustomEvent(s, false, false, data)
      return e
    }

    this.ws.onopen = event => {
      this.dispatch(newEvent('open', event.data))
    }
    this.ws.onmessage = event => {
      this.dispatch(newEvent('message', event.data))
    }
    this.ws.onclose = event => {
      this.reset()
      if (this.forcedClose)
        this.dispatch(newEvent('close', event.data))
      else
        setTimeout(() => this.open(true), 1000)
    }
  }

  reset() {
    this.seenLocalID.clear()
    this.pending_self = true
    this.pending_contacts = new Set(this.contacts.keys())
  }

  send(data) {
    if (this.ws)
      this.ws.send(JSON.stringify(data));
  }

  sync_contacts() {
    if (! (window.contactFactory && this.ws && this.ws.readyState === WebSocket.OPEN)) return
    try {
      if (this.pending_self) {
        const self = accountFactory.getUserName()
        if (self) {
          this.send({
            command: 'self',
            username: self,
          })
          this.pending_self = false
        }
      }
      // TODO potential race when 'self' is not acknowledged
      if (this.pending_contacts.size) {
        for (let username of this.pending_contacts)
          if (this.contacts.has(username)) {
            const x = this.contacts.get(username)
            let y = {
              DisplayName: x.RemarkName || x.DisplayName || x.NickName,
              NickName: x.NickName,
              OwnerUin: x.OwnerUin,
              UserName: x.UserName,
            }
            if (x.VerifyFlag & confFactory.MM_USERATTRVERIFYFALG_BIZ_BRAND // isBrandContact()
              || utilFactory.isShieldUser(username))
              ;
            else if (utilFactory.isRoomContact(username)) { // isRoomContact
              if (x.MemberList) {
                let members = []
                for (let xx of x.MemberList) {
                  const z = this.contacts.get(xx.UserName) || {}
                  const yy = {
                    DisplayName: z.RemarkName || z.DisplayName || z.NickName || xx.RemarkName || xx.DisplayName || xx.NickName,
                    NickName: z.NickName || xx.NickName,
                    Uin: z.Uin || xx.Uin,
                    UserName: z.UserName || xx.UserName,
                  }
                  members.push(yy)
                  //if (xx.UserName.match(/^@d2b7/))
                  //  debugger
                  // prevent a RoomContact from changing his name if he is a member of several groups
                  if (! this.contacts.has(xx.UserName))
                    this.contacts.set(xx.UserName, yy)
                }
                y.MemberList = members
              }
              this.send({
                command: 'room',
                record: y,
              })
            } else {
              this.send({
                command: 'contact',
                friend: x.ContactFlag & confFactory.CONTACTFLAG_CONTACT,
                record: y,
              })
            }
          } else
            this.send({
              command: 'delete_contact',
              username
            })
        this.pending_contacts.clear()
      }
    } catch (ex) {
      console2.error(ex.stack)
      this.send({command: 'web_debug', message: 'sync contact exception: ' + ex.message + "\nstack: " + ex.stack})
    }
  }
}

class Injector {
  static lock(object, key, value) {
    return Object.defineProperty(object, key, {
      get: () => value,
      set: () => {},
    })
  }

  init() {
    if (Common.DEBUG)
      Injector.lock(window, 'console', window.console)
    this.initAngularInjection()
    window.ctrlServer = new CtrlServer()
  }

  initAngularInjection() {
    const self = this;
    const angular = window.angular = {};

    let angularBootstrapReal
    Object.defineProperty(angular, 'bootstrap', {
      set: (real) => (angularBootstrapReal = real),
      get: () => angularBootstrapReal ? function (element, moduleNames) {
        const moduleName = 'webwxApp';
        if (moduleNames.indexOf(moduleName) < 0) return;
        let constants = null;
        let $injector = angular.injector(['ng', 'Services'])
        $injector.invoke(['confFactory', (confFactory) => (constants = confFactory)]);
        angular.module(moduleName).config(['$httpProvider', ($httpProvider) => {
          $httpProvider.defaults.transformResponse.push((value) => {
            return self.transformResponse(value, constants);
          });
        },
        ])

        let ret = angularBootstrapReal.apply(angular, arguments)
        let injector = angular.element(document).injector();
        window.accountFactory = injector.get('accountFactory')
        window.chatFactory = injector.get('chatFactory')
        window.chatroomFactory = injector.get('chatroomFactory')
        window.confFactory = injector.get('confFactory')
        window.contactFactory = injector.get('contactFactory')
        window.emojiFactory = injector.get('emojiFactory')
        window.utilFactory = injector.get('utilFactory')
        window.editArea = angular.element('#editArea').scope()

        // chatFactory#createMessage
        const chatFactoryCreateMessageReal = chatFactory.createMessage
        Object.defineProperty(chatFactory, 'createMessage', {
          set: () => {},
          get: () => function (e) {
            return Injector.chatFactoryCreateMessage.call(chatFactory, chatFactoryCreateMessageReal).apply(null, arguments)
          }
        })

        // chatFactory#messageProcess
        const chatFactoryMessageProcessReal = chatFactory.messageProcess
        Object.defineProperty(chatFactory, 'messageProcess', {
          set: () => {},
          get: () => function(e) {
            return Injector.chatFactoryMessageProcess.call(chatFactory, chatFactoryMessageProcessReal).apply(null, arguments)
          }
        })

        // contactFactory#addContact
        const contactFactoryAddContactReal = contactFactory.addContact
        Object.defineProperty(contactFactory, 'addContact', {
          set: () => {},
          get: () => function(e) {
            return Injector.contactFactoryAddContact.call(contactFactory, contactFactoryAddContactReal).apply(null, arguments)
          }
        })

        // contactFactory#deleteContact
        const contactFactoryDeleteContactReal = contactFactory.deleteContact
        Object.defineProperty(contactFactory, 'deleteContact', {
          set: () => {},
          get: () => function(e) {
            return Injector.contactFactoryDeleteContact.call(contactFactory, contactFactoryDeleteContactReal).apply(null, arguments)
          }
        })

        return ret
      } : angularBootstrapReal
    })
  }

  transformResponse(value, constants) {
    if (!value) return value;

    switch (typeof value) {
      case 'object':
        /* Inject emoji stickers and prevent recalling. */
        return this.checkEmojiContent(value, constants);
    }
    return value;
  }

  checkEmojiContent(value, constants) {
    if (!(value.AddMsgList instanceof Array)) return value;
    value.AddMsgList.forEach((msg) => {
      switch (msg.MsgType) {
        case constants.MSGTYPE_EMOTICON:
          Injector.lock(msg, 'MMDigest', '[Emoticon]');
          Injector.lock(msg, 'MsgType', constants.MSGTYPE_EMOTICON);
          if (msg.ImgHeight >= Common.EMOJI_MAXIUM_SIZE) {
            Injector.lock(msg, 'MMImgStyle', { height: `${Common.EMOJI_MAXIUM_SIZE}px`, width: 'initial' });
          } else if (msg.ImgWidth >= Common.EMOJI_MAXIUM_SIZE) {
            Injector.lock(msg, 'MMImgStyle', { width: `${Common.EMOJI_MAXIUM_SIZE}px`, height: 'initial' });
          }
          break;
        case constants.MSGTYPE_RECALLED:
          Injector.lock(msg, 'MsgType', constants.MSGTYPE_SYS);
          Injector.lock(msg, 'MMActualContent', Common.MESSAGE_PREVENT_RECALL);
          Injector.lock(msg, 'MMDigest', Common.MESSAGE_PREVENT_RECALL);
          break;
      }
    });
    return value;
  }

  static chatFactoryCreateMessage(real) {
    return (e) => {
      let msg = real.call(this, e)
      msg.ClientMsgId = msg.LocalID = msg.MsgId = window.ctrlServer.localID || (utilFactory.now() + Math.random().toFixed(3)).replace(".", "")
      return msg
    }
  }

  static chatFactoryMessageProcess(real) {
    return (e) => {
      let t = this, o = contactFactory.getContact(e.FromUserName, "", !0);
      //@ MOVE 更新未读标记数，标题提醒的代码移动至底部，若消息成功发送到服务端则标记为已读
      if (
      e.MMPeerUserName = t._getMessagePeerUserName(e),
      e.MsgType == confFactory.MSGTYPE_STATUSNOTIFY)
          return void t._statusNotifyProcessor(e);
      if (e.MsgType == confFactory.MSGTYPE_SYSNOTICE)
          return void console.log("MSGTYPE_SYSNOTICE", e.Content);
      if (!(utilFactory.isShieldUser(e.FromUserName) || utilFactory.isShieldUser(e.ToUserName) || e.MsgType == confFactory.MSGTYPE_VERIFYMSG && e.RecommendInfo && e.RecommendInfo.UserName == accountFactory.getUserInfo().UserName)) {
          switch (t._commonMsgProcess(e),
          e.MsgType) {
          case confFactory.MSGTYPE_APP:
              try {
                  t._appMsgProcess(e)
              } catch (n) {
                  console.log("catch _appMsgProcess error", n, e)
              }
              break;
          case confFactory.MSGTYPE_EMOTICON:
              t._emojiMsgProcess(e);
              break;
          case confFactory.MSGTYPE_IMAGE:
              t._imageMsgProcess(e);
              break;
          case confFactory.MSGTYPE_VOICE:
              t._voiceMsgProcess(e);
              break;
          case confFactory.MSGTYPE_VIDEO:
              t._videoMsgProcess(e);
              break;
          case confFactory.MSGTYPE_MICROVIDEO:
              t._mircovideoMsgProcess(e);
              break;
          case confFactory.MSGTYPE_TEXT:
              "newsapp" == e.FromUserName ? t._newsMsgProcess(e) : e.AppMsgType == confFactory.APPMSGTYPE_RED_ENVELOPES ? (e.MsgType = confFactory.MSGTYPE_APP,
              t._appMsgProcess(e)) : e.SubMsgType == confFactory.MSGTYPE_LOCATION ? t._locationMsgProcess(e) : t._textMsgProcess(e);
              break;
          case confFactory.MSGTYPE_RECALLED:
              return void t._recalledMsgProcess(e);
          case confFactory.MSGTYPE_LOCATION:
              t._locationMsgProcess(e);
              break;
          case confFactory.MSGTYPE_VOIPMSG:
          case confFactory.MSGTYPE_VOIPNOTIFY:
          case confFactory.MSGTYPE_VOIPINVITE:
              t._voipMsgProcess(e);
              break;
          case confFactory.MSGTYPE_POSSIBLEFRIEND_MSG:
              t._recommendMsgProcess(e);
              break;
          case confFactory.MSGTYPE_VERIFYMSG:
              t._verifyMsgProcess(e);
              break;
          case confFactory.MSGTYPE_SHARECARD:
              t._shareCardProcess(e);
              break;
          case confFactory.MSGTYPE_SYS:
              t._systemMsgProcess(e);
              break;
          default:
              e.MMDigest = MM.context("938b111")
          }
          //@ PATCH
          let content = ''
          let range = document.createRange()
          range.selectNode(document.body) // Safari
          for (let i = range.createContextualFragment(e.MMActualContent).firstChild; i; i = i.nextSibling) {
              if (i instanceof HTMLImageElement) {
                  do {
                      let emoji = /^emoji emoji(\w+)$/.exec(i.className)
                      if (emoji !== null) {
                          content += String.fromCodePoint(parseInt(emoji[1], 16))
                          break
                      }
                      emoji = /^(\[.+\])_web$/.exec(i.getAttribute('text'))
                      if (emoji !== null) {
                          content += emoji[1]
                          break
                      }
                  } while (0)
              } else if (i instanceof HTMLBRElement)
                  content += '\n'
              else
                  content += utilFactory.htmlDecode(i.textContent)
          }

          e.MMActualContent = utilFactory.hrefEncode(e.MMActualContent);
          let r = contactFactory.getContact(e.MMPeerUserName);
          //@ MOVE 声音提醒、桌面提醒的代码移动至底部，若消息成功发送到服务端则不提醒
          t.addChatMessage(e),
          t.addChatList([e])

          //@ PATCH
          try {
              // 服务端通过WebSocket控制网页版发送消息，无需投递到服务端
              if (window.ctrlServer.seenLocalID.has(e.LocalID))
                  window.ctrlServer.seenLocalID.delete(e.LocalID)
              // 非服务端生成
              else {
                  let sender = contactFactory.getContact(e.MMActualSender)
                  let receiver = contactFactory.getContact(e.MMIsChatRoom ? e.MMPeerUserName : e.ToUserName)
                  if (sender && receiver) {
                      sender = Object.assign({}, sender, {DisplayName: sender.RemarkName || sender.getDisplayName()})
                      receiver = Object.assign({}, receiver, {DisplayName: receiver.RemarkName || receiver.getDisplayName()})
                      delete sender.MemberList
                      delete receiver.MemberList
                      if (e.MMLocationUrl)
                          content = `[位置] ${e.MMLocationDesc} ${e.MMLocationUrl}`
                      else if (e.MsgType == confFactory.MSGTYPE_IMAGE) // 3 图片
                          // e.getMsgImg
                          content = '[图片] ' + 'https://wx.qq.com'+confFactory.API_webwxgetmsgimg + "?MsgID=" + e.MsgId + "&skey=" + encodeURIComponent(accountFactory.getSkey())
                      else if (e.MsgType == confFactory.MSGTYPE_VOICE) // 34 语音
                          content = '[语音] ' + 'https://wx.qq.com'+confFactory.API_webwxgetvoice + "?msgid=" + e.MsgId + "&skey=" + accountFactory.getSkey()
                      else if (e.MsgType == confFactory.MSGTYPE_VERIFYMSG) { // 37 新的朋友
                          let info = e.RecommendInfo
                          let gender = info.Sex == 1 ? '男' : info.Sex == 2 ? '女' : '未知'
                          content = `[新的朋友] 昵称：${info.NickName} 性别：${gender} 省：${info.Province} 介绍：${info.Content} 头像：https://wx.qq.com${info.HeadImgUrl}`
                      }
                      else if (e.MsgType == confFactory.MSGTYPE_SHARECARD) { // 42 名片
                          let info = e.RecommendInfo
                          let gender = info.Sex == 1 ? '男' : info.Sex == 2 ? '女' : '未知'
                          content = `[名片] 昵称：${info.NickName} 性别：${gender} 省：${info.Province} 头像：https://wx.qq.com${info.HeadImgUrl}`
                      }
                      else if (e.MsgType == confFactory.MSGTYPE_VIDEO) // 43 视频
                          // e.getMsgVideo
                          content = '[视频] ' + 'https://wx.qq.com'+confFactory.API_webwxgetvideo + "?msgid=" + e.MsgId + "&skey=" + encodeURIComponent(accountFactory.getSkey())
                      else if (e.MsgType == confFactory.MSGTYPE_EMOTICON) // 47 动画表情
                          // e.getMsgImg + HTML
                          content = '[动画表情] ' + 'https://wx.qq.com'+confFactory.API_webwxgetmsgimg + "?MsgID=" + e.MsgId + "&skey=" + encodeURIComponent(accountFactory.getSkey())
                      else if (e.MsgType == confFactory.MSGTYPE_LOCATION) // 48 位置 目前尚未实现
                          content = '[位置]'
                      else if (e.MsgType == confFactory.MSGTYPE_APP) { // 49
                          if (e.AppMsgType == confFactory.APPMSGTYPE_ATTACH) {
                              content = `[文件] filename: ${e.FileName} size: ${e.MMAppMsgFileSize} url: ${e.MMAppMsgDownloadUrl}`
                          } else {
                              let doms = $.parseHTML(content.replace(/&lt;?/g,'<').replace(/&gt;?/g,'>').replace(/&amp;?/g,'&'))
                              content = '[App] ' + $('appmsg>title', doms).text() + ' ' + $('appmsg>url', doms).text()
                          }
                      }
                      else if (e.MsgType == confFactory.MSGTYPE_MICROVIDEO) // 62 小视频
                          content = '[小视频] ' + 'https://wx.qq.com'+confFactory.API_webwxgetvideo + "?msgid=" + e.MsgId + "&skey=" + encodeURIComponent(accountFactory.getSkey())
                      else if (e.MsgType == confFactory.MSGTYPE_SYS) // 10000 系统，如：“您已添加了xxx，现在可以开始聊天了。”、“xx邀请了yy加入了群聊。”、“如需将文字消息的语言翻译成系统语言，可以长按消息后选择"翻译"”
                          content = '[系统] ' + content
                      else if (e.MsgType == confFactory.MSGTYPE_RECALLED) // 10002 撤回
                          content = '[撤回了一条消息]'
                      if (e.MMIsChatRoom) {
                          window.ctrlServer.send({command: 'room_message',
                                  sender: sender,
                                  receiver: receiver,
                                  message: content,
                                  time: e.CreateTime
                          })
                          // 发送成功(无异常)则标记为已读
                          e.MMUnread = false
                      } else if (! sender.isBrandContact()) {
                          window.ctrlServer.send({command: 'message',
                                  sender: sender,
                                  receiver: receiver,
                                  message: content,
                                  time: e.CreateTime
                          })
                          e.MMUnread = false
                      }
                  }
              }
          } catch (ex) {
              window.ctrlServer.send({command: 'web_debug', message: 'message exception: '  + ex.message + "\nstack: " + ex.stack})
              console2.error(ex.stack)
          }

          if (e.MMUnread) {
              e.MMIsSend || r && (r.isMuted() || r.isBrandContact()) || e.MsgType == confFactory.MSGTYPE_SYS || (accountFactory.isNotifyOpen() && t._notify(e))
              !o || o.isMuted() || o.isSelf() || o.isShieldUser() || o.isBrandContact() || titleRemind.increaseUnreadMsgNum()
              accountFactory.isSoundOpen() && utilFactory.initMsgNoticePlayer(confFactory.RES_SOUND_RECEIVE_MSG)
          }
      }
    }
  }

  static contactFactoryAddContact(real) {
    return (e) => {
      const ret = real.call(this, e)
      // this rule filters those `isShieldUser` groups and strangers
      // friends may exist both in window._contacts and window.strangerContacts, and they may be added twice, one with ContactFlag unset and the other with ContactFlag set
      if (e.ContactFlag & confFactory.CONTACTFLAG_CONTACT || ! (e.UserName in _strangerContacts)) {
        ctrlServer.contacts.set(e.UserName, e)
        ctrlServer.pending_contacts.add(e.UserName)
      }
      return ret
    }
  }

  static contactFactoryDeleteContact(real) {
    return (e) => {
      ctrlServer.contacts.delete(e.UserName)
      ctrlServer.pending_contacts.add(e.UserName)
      return real.call(this, e)
    }
  }
}

new Injector().init()
