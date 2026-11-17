const P = require('./pitchcore.js');
const sr = 48000;
function tone(f, sec, harm=[1], amp=0.5, vib=0){ const n=Math.floor(sec*sr), a=new Float32Array(n); for(let i=0;i<n;i++){let t=i/sr,ph=vib?vib*Math.sin(2*Math.PI*5.5*t)/5.5:0; for(let h=0;h<harm.length;h++) a[i]+=harm[h]*amp*Math.sin(2*Math.PI*f*(h+1)*t+ (h+1)*f*ph/f*0 + 2*Math.PI*(h+1)*f*0.01*ph*0);} return a;}
const cases=[[110,'A2'],[261.63,'C4'],[440,'A4'],[82.41,'E2'],[329.63,'E4'],[1046.5,'C6'],[155.56,'D#3'],[452.9,'A4 (+50ish)']];
for(const [f,exp] of cases){ const buf=tone(f,0.1,[1,0.5,0.3,0.2]).slice(0,2048); const p=P.yin(buf,sr); const ni=P.noteInfo(p.freq); console.log(f,'->',ni.name,ni.cents+'c',p.freq.toFixed(2),'clarity',p.clarity.toFixed(2),'expect',exp); }
// segment test: melody A3 C4 E4 with silence
const seq=[[220,0.6],[0,0.2],[261.63,0.5],[329.63,0.7],[0,0.3],[110,0.4]];
let parts=seq.map(([f,d])=>f?tone(f,d,[1,0.6,0.4,0.3]):new Float32Array(Math.floor(d*sr)));
let len=parts.reduce((s,a)=>s+a.length,0), sig=new Float32Array(len), o=0; for(const a of parts){sig.set(a,o);o+=a.length;}
const r=P.analyseSignal(sig,sr); console.log(r.notes.map(n=>`${n.name}${n.cents>=0?'+':''}${n.cents} @${n.start.toFixed(2)} ${n.dur.toFixed(2)}s`).join(' | '));
// noise robustness
for(let i=0;i<sig.length;i++) sig[i]+= (Math.random()-0.5)*0.05;
console.log('noisy:',P.analyseSignal(sig,sr).notes.map(n=>n.name).join(' '));
// chord: C major and A minor, E5 power
function chordSpec(fs){ const N=8192; const x=new Float32Array(N); fs.forEach(f=>{for(let i=0;i<N;i++){for(let h=1;h<=4;h++) x[i]+=Math.sin(2*Math.PI*f*h*i/sr)/(h*h);}}); // naive DFT magnitude via FFT
 const re=Float64Array.from(x.map((v,i)=>v*(0.5-0.5*Math.cos(2*Math.PI*i/(N-1))))), im=new Float64Array(N); fft(re,im); const mag=new Float32Array(N/2); for(let i=0;i<N/2;i++) mag[i]=Math.hypot(re[i],im[i]); return P.guessChord(P.chromaFromSpectrum(mag,sr,N)); }
function fft(re,im){const n=re.length;for(let i=1,j=0;i<n;i++){let b=n>>1;for(;j&b;b>>=1)j^=b;j^=b;if(i<j){[re[i],re[j]]=[re[j],re[i]];[im[i],im[j]]=[im[j],im[i]];}}for(let len=2;len<=n;len<<=1){const a=-2*Math.PI/len;for(let i=0;i<n;i+=len)for(let k=0;k<len/2;k++){const c=Math.cos(a*k),s=Math.sin(a*k);const ur=re[i+k],ui=im[i+k];const vr=re[i+k+len/2]*c-im[i+k+len/2]*s,vi=re[i+k+len/2]*s+im[i+k+len/2]*c;re[i+k]=ur+vr;im[i+k]=ui+vi;re[i+k+len/2]=ur-vr;im[i+k+len/2]=ui-vi;}}}
const m=P.midiName, f=x=>440*2**((x-69)/12);
console.log('C major', chordSpec([f(48),f(52),f(55),f(60)]).name);
console.log('A minor', chordSpec([f(45),f(52),f(57),f(60),f(64)]).name);
console.log('G7', chordSpec([f(43),f(47),f(50),f(53)]).name);
console.log('E5', chordSpec([f(40),f(47),f(52)]).name);
console.log('D major', chordSpec([f(50),f(57),f(62),f(66)]).name);
console.log('voice', P.guessVoice(48,72), P.guessVoice(43,67), P.guessVoice(60,84), P.guessVoice(47,76));
// decimated path tests incl. 44.1k, high notes, vibrato voice-like
for (const SR of [44100, 48000]) {
  const out=[];
  for (const [f] of [[82.41],[110],[261.63],[440],[880],[1046.5],[1318.5]]) {
    const n=Math.floor(0.8*SR), a=new Float32Array(n); let ph=0;
    for(let i=0;i<n;i++){ const ff=f*Math.pow(2,0.3/12*Math.sin(2*Math.PI*5.5*i/SR)); ph+=2*Math.PI*ff/SR; a[i]=0.5*Math.sin(ph)+0.3*Math.sin(2*ph)+0.2*Math.sin(3*ph)+0.1*Math.sin(4*ph);}
    const r=P.analyseSignal(a,SR); out.push(f+'->'+r.notes.map(x=>x.name+(x.cents>=0?'+':'')+x.cents).join(','));
  }
  console.log(SR, out.join('  '));
}
let t0=Date.now(); const big=new Float32Array(48000*30); for(let i=0;i<big.length;i++) big[i]=0.5*Math.sin(2*Math.PI*220*i/48000); P.analyseSignal(big,48000); console.log('30s clip ms', Date.now()-t0);
