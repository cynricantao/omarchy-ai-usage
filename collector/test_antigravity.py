import unittest, tempfile, sqlite3
from pathlib import Path
import adapters

def var(v):
 b=b''
 while v>127:b+=bytes([(v&127)|128]);v>>=7
 return b+bytes([v])
def num(n,v):return var(n<<3)+var(v)
def msg(n,v):return var((n<<3)|2)+var(len(v))+v
class AntigravityTest(unittest.TestCase):
 def test_native_generation_usage_once_without_content(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);(root/'conversations').mkdir();p=root/'conversations/session.db'
   c=sqlite3.connect(p);c.executescript('create table steps(idx integer,metadata blob);create table gen_metadata(idx integer,data blob);')
   usage=num(2,100)+num(3,20)+num(5,30)+num(9,12)+num(10,8)
   chat=msg(1,b'SECRET PROMPT')+msg(4,usage)+msg(19,b'gemini-3.8-flash')
   c.execute('insert into gen_metadata values(?,?)',(0,msg(1,chat)+msg(2,var(1)+var(2))))
   for idx in (1,2):c.execute('insert into steps values(?,?)',(idx,msg(1,num(1,1791200000))+msg(9,usage)))
   c.commit();c.close();before=p.read_bytes()
   result=adapters.collect({'id':'antigravity','homes':[str(root)]})
   self.assertEqual(len(result['events']),1)
   e=result['events'][0];self.assertEqual(e['model'],'gemini-3.8-flash');self.assertEqual(e['occurred_at'],1791200000)
   self.assertEqual(e['usage'],{'input':70,'output':20,'cache_read':30,'cache_write':None,'total':120})
   self.assertNotIn('SECRET',str(result));self.assertEqual(p.read_bytes(),before)
   self.assertEqual(adapters.collect({'id':'antigravity','homes':[str(root)]})['events'][0]['id'],e['id'])
if __name__=='__main__':unittest.main()
