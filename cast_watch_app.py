from flask import Flask,render_template_string
from flask_sock import Sock
import json,random,string
app=Flask(__name__);sock=Sock(app);rooms={}
HTML=r"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>Cast & Watch</title><style>*{box-sizing:border-box}body{margin:0;background:#090b10;color:#fff;font-family:system-ui,-apple-system,Segoe UI,sans-serif;min-height:100vh;display:grid;place-items:center}main{width:min(900px,100%);padding:18px}.card{background:#11151d;border:1px solid #252b36;border-radius:22px;padding:22px;box-shadow:0 15px 50px #0007}h1{text-align:center;margin:4px 0 8px;font-size:28px}p{color:#9da6b5;text-align:center}.modes{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:25px}.btn{border:0;border-radius:16px;padding:18px;font-size:18px;font-weight:700;background:#fff;color:#090b10;cursor:pointer}.btn2{background:#1b222d;color:#fff;border:1px solid #303846}.hidden{display:none}.input{width:100%;padding:15px;border-radius:13px;border:1px solid #343b49;background:#0b0e14;color:#fff;font-size:18px;text-align:center;outline:0}.code{font-size:38px;font-weight:800;letter-spacing:8px;text-align:center;margin:18px 0}.row{display:flex;gap:10px;margin-top:12px}.row>*{flex:1}.status{text-align:center;padding:10px;color:#9da6b5}.pick{display:block;text-align:center;border:1px dashed #465063;border-radius:15px;padding:18px;cursor:pointer;margin-top:16px}.pick input{display:none}.video{width:100%;max-height:70vh;background:#000;border-radius:16px;display:block}.controls{display:flex;gap:8px;align-items:center;margin-top:10px}.controls button{background:#1b222d;color:#fff;border:1px solid #303846;border-radius:11px;padding:11px 14px;font-size:17px}.seek{flex:1}.vol{width:100px}.back{margin-bottom:12px;background:none;border:0;color:#aeb7c6;cursor:pointer;font-size:15px}@media(max-width:600px){.modes{grid-template-columns:1fr}.controls{flex-wrap:wrap}.seek{order:3;flex-basis:100%}.vol{width:80px}}</style></head><body><main><section class="card" id="home"><h1>🎬 Cast & Watch</h1><p>एक device से video cast करें और दूसरे पर देखें</p><div class="modes"><button class="btn" onclick="mode('cast')">📡 CAST</button><button class="btn btn2" onclick="mode('watch')">📺 WATCH</button></div></section><section class="card hidden" id="cast"><button class="back" onclick="location.reload()">← Home</button><h1>📡 Cast</h1><div class="status" id="cs">Room बना रहा है...</div><div class="code" id="code">------</div><label class="pick">🎞️ Video चुनें<input id="file" type="file" accept="video/*"></label><video id="local" class="video hidden" controls playsinline></video><div class="status" id="cc">दूसरे device पर WATCH खोलें</div></section><section class="card hidden" id="watch"><button class="back" onclick="location.reload()">← Home</button><h1>📺 Watch</h1><div id="join"><input class="input" id="room" maxlength="6" inputmode="numeric" placeholder="6 digit Cast Code"><div class="row"><button class="btn" onclick="join()">CONNECT</button></div></div><div class="status" id="ws">Code डालकर Connect करें</div><video id="remote" class="video hidden" playsinline></video><div class="controls hidden" id="ctrl"><button onclick="cmd('back')">↶10</button><button onclick="cmd('play')">▶/⏸</button><button onclick="cmd('fwd')">10↷</button><input class="seek" id="seek" type="range" min="0" max="100" value="0" oninput="seek(this.value)"><input class="vol" type="range" min="0" max="1" step=".01" value="1" oninput="volume(this.value)"><button onclick="full()">⛶</button></div></section></main><script>
let socket=null,pc=null,roomId=null,role=null,localVideo=document.getElementById('local'),remote=document.getElementById('remote');
const ice={iceServers:[{urls:'stun:stun.l.google.com:19302'},{urls:'stun:stun1.l.google.com:19302'}]};
const signal=()=>new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws');
function mode(x){home.classList.add('hidden');document.getElementById(x).classList.remove('hidden');if(x==='cast')startCast()}
function send(o){if(socket&&socket.readyState===1)socket.send(JSON.stringify(o))}
function startCast(){role='cast';socket=signal();socket.onopen=()=>send({t:'create'});socket.onmessage=async e=>{let m=JSON.parse(e.data);if(m.t==='room'){roomId=m.id;code.textContent=roomId;cs.textContent='Room तैयार है'}if(m.t==='answer'){await pc.setRemoteDescription(m.sdp);cc.textContent='🟢 Watch connected'}if(m.t==='ice'&&pc)try{await pc.addIceCandidate(m.c)}catch{}if(m.t==='control'&&localVideo){if(m.c==='play'){if(localVideo.paused)localVideo.play();else localVideo.pause()}if(m.c==='back')localVideo.currentTime=Math.max(0,localVideo.currentTime-10);if(m.c==='fwd')localVideo.currentTime=Math.min(localVideo.duration||0,localVideo.currentTime+10);if(m.c==='seek')localVideo.currentTime=(+m.v/100)*(localVideo.duration||0);if(m.c==='volume')localVideo.volume=+m.v}}}
file.onchange=async e=>{let f=e.target.files[0];if(!f)return;localVideo.src=URL.createObjectURL(f);localVideo.classList.remove('hidden');pc=new RTCPeerConnection(ice);let stream=localVideo.captureStream();stream.getTracks().forEach(t=>pc.addTrack(t,stream));pc.onicecandidate=e=>e.candidate&&send({t:'ice',c:e.candidate});let offer=await pc.createOffer();await pc.setLocalDescription(offer);send({t:'offer',sdp:pc.localDescription});cc.textContent='Video ready, WATCH device connect कर सकता है'}
async function join(){roomId=document.getElementById('room').value.trim();if(!/^\d{6}$/.test(roomId)){ws.textContent='❌ 6 digit code डालें';return}socket=signal();socket.onopen=()=>send({t:'join',id:roomId});socket.onmessage=async e=>{let m=JSON.parse(e.data);if(m.t==='ok'){joinBox();ws.textContent='🔄 Connecting...'}if(m.t==='offer'){pc=new RTCPeerConnection(ice);pc.ontrack=e=>{remote.srcObject=e.streams[0];remote.classList.remove('hidden');ctrl.classList.remove('hidden');ws.textContent='🟢 Connected';remote.play().catch(()=>{})};pc.onicecandidate=e=>e.candidate&&send({t:'ice',c:e.candidate});let ans=await pc.createAnswer();await pc.setLocalDescription(ans);send({t:'answer',sdp:pc.localDescription})}if(m.t==='ice'&&pc)try{await pc.addIceCandidate(m.c)}catch{}if(m.t==='error')ws.textContent='❌ '+m.msg}}
function joinBox(){document.getElementById('join').classList.add('hidden')}
function cmd(c){send({t:'control',c:c})}
function seek(v){send({t:'control',c:'seek',v:v})}
function volume(v){send({t:'control',c:'volume',v:v})}
function full(){remote.requestFullscreen?.()}
remote.addEventListener('timeupdate',()=>{if(remote.duration)seek.value=remote.currentTime/remote.duration*100})
</script></body></html>"""
@app.route("/")
def index():return render_template_string(HTML)
def new_id():
    while True:
        x=''.join(random.choices(string.digits,k=6))
        if x not in rooms:return x
@sock.route("/ws")
def websocket(c):
    rid=None
    try:
        while True:
            raw=c.receive()
            if raw is None:break
            m=json.loads(raw);t=m.get("t")
            if t=="create":
                rid=new_id();rooms[rid]={"cast":c,"watch":None};c.send(json.dumps({"t":"room","id":rid}))
            elif t=="join":
                rid=m.get("id","");r=rooms.get(rid)
                if not r or not r.get("cast"):c.send(json.dumps({"t":"error","msg":"Room नहीं मिला"}));continue
                r["watch"]=c;c.send(json.dumps({"t":"ok"}))
            elif t in ("offer","answer","ice","control"):
                r=rooms.get(rid)
                if r:
                    target=r.get("watch") if c is r.get("cast") else r.get("cast")
                    if target:target.send(json.dumps(m))
    except Exception:pass
    finally:
        if rid and rid in rooms:
            r=rooms[rid]
            if r.get("cast") is c:r["cast"]=None
            if r.get("watch") is c:r["watch"]=None
            if not r["cast"] and not r["watch"]:rooms.pop(rid,None)
if __name__=="__main__":app.run(host="0.0.0.0",port=5000)
