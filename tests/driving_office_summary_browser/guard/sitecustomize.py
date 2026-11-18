import socket
_original=socket.socket.connect

def guarded(self,address):
 if not isinstance(address,tuple) or len(address)<2 or address[0] not in ('127.0.0.1','localhost') or address[1] not in (51238,55439):
  raise RuntimeError('ISOLATED_EXTERNAL_CONNECTION_DENIED')
 return _original(self,address)
socket.socket.connect=guarded
