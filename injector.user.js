// ==UserScript==
// @name         wechatircd JS injector
// @namespace    https://github.com/MaskRay/wechatircd
// @version      0.2
// @description  inject client side JS of wechatircd to https://wx.qq.com
// @author       MaskRay
// @match        https://wx.qq.com/
// @match        https://wx.qq.com/?*
// @match        https://wx2.qq.com/
// @match        https://wx2.qq.com/?*
// @run-at       document-start
// @downloadURL  https://github.com/MaskRay/wechatircd/raw/master/injector.user.js
// @updateURL    https://github.com/MaskRay/wechatircd/raw/master/injector.user.js
// ==/UserScript==

var script = document.createElement('script')
script.src = 'https://127.0.0.1:9000/injector.js'
document.getElementsByTagName('head')[0].appendChild(script)
