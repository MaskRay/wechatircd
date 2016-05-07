function MyWebSocket(url) {
  var ws
  var eventTarget = document.createElement('div')
  eventTarget.addEventListener('message', data => this.onmessage(data))
  var forcedClose = false
  var dispatch = eventTarget.dispatchEvent.bind(eventTarget)

  function newEvent(s, data) {
    var e = document.createEvent('CustomEvent')
    e.initCustomEvent(s, false, false, data)
    return e
  }

  this.open = reconnect => {
    ws = new WebSocket(url)
    ws.onmessage = event => {
      dispatch(newEvent('message', event.data))
    }
    ws.onclose = event => {
      if (forcedClose)
        dispatch(newEvent('close', event.data))
      else
        setTimeout(() => this.open(), 1000)
    }
  }

  this.close = () => {
    forcedClose = true
    if (ws)
      ws.close()
  }

  this.send = data => {
    if (ws)
      ws.send(data)
  }

  this.open(false)
}

var ws = new MyWebSocket('ws://127.1:8080')
ws.onmessage = data => {
  console.dir(data.detail)
}
setInterval(() => {
  var token = document.getElementById('token').value
  try {
    if (token)
      ws.send(JSON.stringify({token: token, command: 'user', record: {
        'RemarkName': 'remark',
        'NickName': 'nick',
        'UserName': '@friend',
      }}))
      ws.send(JSON.stringify({token: token, command: 'user', record: {
        'NickName': 'user',
        'UserName': '@user',
      }}))
      ws.send(JSON.stringify({token: token, command: 'room', record: {
        'RemarkName': 'room',
        'NickName': 'myroom',
        'UserName': '@@myroom',
        'MemberList': [ {
          'NickName': 'user',
          'UserName': '@user',
        } ]
      }}))
  } catch (e) {
  }
}, 3000)
