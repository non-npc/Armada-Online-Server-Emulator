import tempfile, unittest, sqlite3, struct, urllib.request, urllib.error, re
from pathlib import Path
from login import Accounts
from admin import mutate, start_admin
class AdminTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(); self.path=Path(self.temp.name)/'accounts.sqlite3'
  with Accounts(self.path): pass
 def tearDown(self): self.temp.cleanup()
 def login(self,name,password):
  payload=bytearray(44); payload[0]=100; payload[9:9+len(name)]=name.encode(); payload[25:25+len(password)]=password.encode()
  with Accounts(self.path) as a: return a.login(bytes(payload))
 def test_account_lifecycle_and_login(self):
  mutate(self.path,dict(action='account_save',name='alice',password='secret'))
  _,pid=self.login('alice','secret')
  mutate(self.path,dict(action='account_save',old='alice',name='renamed',password=''))
  self.assertEqual(self.login('renamed','secret')[1],pid)
  mutate(self.path,dict(action='account_save',old='renamed',name='renamed',password='changed'))
  with self.assertRaises(PermissionError): self.login('renamed','secret')
  self.login('renamed','changed')
  mutate(self.path,dict(action='account_delete',old='renamed',confirm='yes'))
  with self.assertRaises(PermissionError): self.login('renamed','changed')
  self.assertTrue(list((self.path.parent/'backups').glob('*.sqlite3')))
 def test_character_and_cascade(self):
  data=dict(action='character_save',player_id='1',slot='0',name='Pilot',race='1',ship='2',intro_completed='1',sector='3',position_x='100',position_z='200')
  mutate(self.path,data)
  payload,_=self.login('player','player'); self.assertEqual(payload[12],1); self.assertEqual(payload[13:18],b'Pilot')
  data['name']='Captain'; mutate(self.path,data)
  mutate(self.path,dict(action='character_delete',player_id='1',slot='0',confirm='yes'))
  self.assertEqual(self.login('player','player')[0][12],0)
  mutate(self.path,data); mutate(self.path,dict(action='account_delete',old='player',confirm='yes'))
  with Accounts(self.path) as a:
   self.assertEqual(a.db.execute('SELECT count(*) FROM accounts').fetchone()[0],0)
   self.assertEqual(a.db.execute('SELECT count(*) FROM characters').fetchone()[0],0)
 def test_validation(self):
  for name,password in [('bad name','x'),('alice','x'*16),('alice','')]:
   with self.assertRaises(ValueError): mutate(self.path,dict(action='account_save',name=name,password=password))
  with self.assertRaises(ValueError): mutate(self.path,dict(action='account_delete',old='player'))
  self.login('player','player')
 def test_http_form_and_csrf(self):
  server=start_admin(self.path,0); url=f'http://127.0.0.1:{server.server_port}/'
  try:
   page=urllib.request.urlopen(url).read().decode(); token=re.search('name="csrf" value="([^"]+)"',page)[1]
   with self.assertRaises(urllib.error.HTTPError) as error: urllib.request.urlopen(url,data=b'action=account_delete&old=player&confirm=yes')
   self.assertEqual(error.exception.code,403)
   response=urllib.request.urlopen(url,data=f'csrf={token}&action=account_save&name=webuser&password=secret'.encode())
   self.assertIn(b'webuser',response.read()); self.login('webuser','secret')
  finally: server.shutdown(); server.server_close()
if __name__=='__main__': unittest.main()
