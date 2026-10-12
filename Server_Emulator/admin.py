"""Local browser administration; passwords use the game's existing PBKDF2 format."""
import hashlib, html, secrets, sqlite3, threading, re, struct
from contextlib import closing
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs
from pathlib import Path
from version import __version__
from login import Accounts

FIELDS = ['name','race','ship','intro_completed','sector','position_x','position_z','last_target_x','last_target_z']
def mutate(path, form):
    action = form.get('action','')
    with closing(sqlite3.connect(path)) as db, db:
        if action in ('account_save','account_delete'):
            old = form.get('old','')
            if old and not db.execute('SELECT 1 FROM accounts WHERE name=?',(old,)).fetchone(): raise ValueError('Account no longer exists')
            if action == 'account_save':
                name, password = form.get('name','').strip(), form.get('password','')
                if not re.fullmatch(r'[A-Za-z0-9_]{1,15}',name): raise ValueError('Login name must be 1–15 ASCII letters, numbers or underscores')
                if (not old or password) and (not 1 <= len(password) <= 15 or not password.isascii() or '\0' in password): raise ValueError('Password must be 1–15 ASCII characters')
                if db.execute('SELECT 1 FROM accounts WHERE name=? AND name<>?',(name,old)).fetchone(): raise ValueError('Login name already exists')
            elif form.get('confirm') != 'yes': raise ValueError('Check the deletion confirmation box')
        elif action in ('character_save','character_delete'):
            pid, slot = int(form['player_id']), int(form['slot'])
            if not 0 <= slot < 6 or not db.execute('SELECT 1 FROM accounts WHERE player_id=?',(pid,)).fetchone(): raise ValueError('Invalid account or slot')
            if action == 'character_save':
                name = form.get('name','').strip()
                if not 2 <= len(name) <= 15 or not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*(?: [A-Za-z0-9]+)?',name): raise ValueError('Character name must match game naming rules (2–15 characters)')
                values = [name] + [int(form[f]) if form.get(f,'').strip() else None for f in FIELDS[1:]]
                race,ship,intro,sector = values[1:5]
                if race not in range(6) or ship not in range(64) or intro not in (0,1) or sector not in (None,1,2,3,4,5,50,51,52): raise ValueError('Invalid race, ship, intro flag or verified sector')
                if any(v is not None and not -(2**31) <= v < 2**31 for v in values[5:]): raise ValueError('Coordinates must fit signed 32-bit integers')
                if (values[5] is None) != (values[6] is None): raise ValueError('Provide both position coordinates or neither')
            elif form.get('confirm') != 'yes': raise ValueError('Check the deletion confirmation box')
        else: raise ValueError('Unknown action')
        backup_dir = Path(path).parent/'backups'; backup_dir.mkdir(exist_ok=True)
        backup_path=backup_dir/('admin_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3')
        with closing(sqlite3.connect(backup_path)) as backup: db.backup(backup)
        if action == 'account_delete':
            pid=db.execute('SELECT player_id FROM accounts WHERE name=?',(old,)).fetchone()[0]
            db.execute('DELETE FROM character_saves WHERE player_id=?',(pid,)); db.execute('DELETE FROM characters WHERE player_id=?',(pid,)); db.execute('DELETE FROM accounts WHERE name=?',(old,))
        elif action == 'account_save':
            if old: db.execute('UPDATE accounts SET name=? WHERE name=?',(name,old))
            else:
                pid=db.execute('SELECT COALESCE(MAX(player_id),0)+1 FROM accounts').fetchone()[0]
                if pid >= 2**24: raise ValueError('Player ID limit reached')
                db.execute('INSERT INTO accounts(name,player_id) VALUES (?,?)',(name,pid))
            if password:
                salt=secrets.token_bytes(16); digest=hashlib.pbkdf2_hmac('sha256',password.encode('ascii'),salt,200000)
                db.execute('UPDATE accounts SET salt=?,password_hash=? WHERE name=?',(salt,digest,name))
        elif action == 'character_delete':
            db.execute('DELETE FROM character_saves WHERE player_id=? AND slot=?',(pid,slot))
            db.execute('DELETE FROM characters WHERE player_id=? AND slot=?',(pid,slot))
        else:
            db.execute('INSERT INTO characters(player_id,slot,'+','.join(FIELDS)+') VALUES ('+','.join('?' for _ in range(11))+') ON CONFLICT(player_id,slot) DO UPDATE SET '+','.join(f+'=excluded.'+f for f in FIELDS),(pid,slot,*values))

def start_admin(path, port=8102):
    with Accounts(path): pass
    token=secrets.token_urlsafe(32)
    esc=lambda value: html.escape(str(value if value is not None else ''),quote=True)
    def field(name,value='',kind='text'):
        return f'<label>{esc(name)} <input name="{esc(name)}" type="{kind}" value="{esc(value)}"></label>'
    def form(action,body):
        return '<form method="post" action="/"><input type="hidden" name="csrf" value="'+token+'"><input type="hidden" name="action" value="'+action+'">'+body+'</form>'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def respond(self,status,body):
            payload=body.encode('utf-8'); self.send_response(status)
            self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(payload)))
            self.send_header('Cache-Control','no-store'); self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
            self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(payload)
        def valid_host(self): return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')
        def do_GET(self):
            if not self.valid_host(): return self.respond(403,'Invalid host')
            if self.path != '/': return self.respond(404,'Not found')
            body=f'<h1>Armada server administration <small>{__version__}</small></h1><p>Local administrator access. Stop the game server or log players out before editing their data. The updated patched client saves character snapshots, resource balance and five shop power slots automatically.</p><h2>Create account</h2>'
            body+=form('account_save',field('name')+field('password',kind='password')+'<button>Create account</button>')
            with closing(sqlite3.connect(path)) as db, db:
                for name,pid in db.execute('SELECT name,player_id FROM accounts ORDER BY name'):
                    body+=f'<section><h2>{esc(name)} · player {pid}</h2>'
                    body+=form('account_save',f'<input type="hidden" name="old" value="{esc(name)}">'+field('name',name)+field('password',kind='password')+'<small>Blank password keeps the existing password.</small><button>Save account</button>')
                    body+=form('account_delete',f'<input type="hidden" name="old" value="{esc(name)}"><label><input type="checkbox" name="confirm" value="yes"> Delete this account and all its characters</label><button>Delete account</button>')
                    chars={r[0]:r[1:] for r in db.execute('SELECT slot,'+','.join(FIELDS)+' FROM characters WHERE player_id=?',(pid,))}
                    for slot in range(6):
                        vals=chars.get(slot,['',0,0,0,None,None,None,None,None])
                        body+=f'<details><summary>Slot {slot+1}: {esc(vals[0]) or "empty"}</summary>'
                        saved=db.execute('SELECT saved_at,extra FROM character_saves WHERE player_id=? AND slot=?',(pid,slot)).fetchone()
                        if saved:
                            body+='<p>Gameplay snapshot saved: '+esc(saved[0])+'</p>'
                            if saved[1]:
                                balance=struct.unpack_from('<I',saved[1])[0]
                                powers=sum(bool(struct.unpack_from('<I',saved[1],4+i*20)[0]&1) for i in range(5))
                                body+=f'<p>Saved resource balance: {balance} · active powers: {powers}/5</p>'
                        elif slot in chars:
                            body+='<p>No gameplay snapshot received yet. Use the updated patched client and play until an autosave occurs.</p>'

                        hidden=f'<input type="hidden" name="player_id" value="{pid}"><input type="hidden" name="slot" value="{slot}">'
                        body+=form('character_save',hidden+''.join(field(f,v,'text' if f=='name' else 'number') for f,v in zip(FIELDS,vals))+'<button>Save character</button>')
                        if slot in chars: body+=form('character_delete',hidden+'<label><input type="checkbox" name="confirm" value="yes"> Confirm character deletion</label><button>Delete character</button>')
                        body+='</details>'
                    body+='</section>'
            self.respond(200,'<!doctype html><meta charset="utf-8"><title>Armada admin</title><style>body{font:16px system-ui;max-width:1000px;margin:30px auto;background:#101827;color:#edf2f7}section,form{padding:14px;margin:12px 0;border:1px solid #526078}label{display:inline-block;margin:8px}input{padding:6px;max-width:170px}button{padding:8px;cursor:pointer}summary{padding:12px;cursor:pointer}small{display:block}</style>'+body)
        def do_POST(self):
            if not self.valid_host() or self.path != '/': return self.respond(403,'Invalid request')
            origin=self.headers.get('Origin')
            if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'): return self.respond(403,'Invalid origin')
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0 < size <= 8192: raise ValueError('Invalid request size')
                form_data={k:v[0] for k,v in parse_qs(self.rfile.read(size).decode('utf-8'),keep_blank_values=True).items()}
                if not secrets.compare_digest(form_data.get('csrf',''),token): return self.respond(403,'Invalid form token; reload the page')
                mutate(path,form_data)
            except (ValueError,KeyError,sqlite3.IntegrityError) as error: return self.respond(400,'<p>'+esc(error)+'</p><a href="/">Back to administration</a>')
            self.send_response(303); self.send_header('Location','/'); self.end_headers()
    server=HTTPServer(('127.0.0.1',port),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    print(f'Account administration: http://127.0.0.1:{server.server_port}/',flush=True)
    return server
