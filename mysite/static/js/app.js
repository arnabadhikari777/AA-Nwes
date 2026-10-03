(function(){
'use strict';
var $=function(s,r){return (r||document).querySelector(s)},$$=function(s,r){return Array.prototype.slice.call((r||document).querySelectorAll(s))};
var store={get:function(k,d){try{return JSON.parse(localStorage.getItem(k))||d}catch(e){return d}},set:function(k,v){try{localStorage.setItem(k,JSON.stringify(v))}catch(e){}}};
function toast(m){var t=$('#toast');if(!t)return;t.textContent=m;t.classList.add('show');clearTimeout(toast.t);toast.t=setTimeout(function(){t.classList.remove('show')},2600)}
var csrf=(document.querySelector('meta[name=csrf-token]')||{}).content;

/* theme */
function setTheme(t){document.documentElement.setAttribute('data-theme',t);try{localStorage.setItem('aa_theme',t)}catch(e){}var b=$('#theme-btn');if(b)b.textContent=t==='dark'?'☀️':'🌙'}
setTheme(document.documentElement.getAttribute('data-theme')||'light');
$('#theme-btn')&&$('#theme-btn').addEventListener('click',function(){setTheme(document.documentElement.getAttribute('data-theme')==='dark'?'light':'dark')});

/* mobile menu */
var mb=$('#menu-btn'),nav=$('#cat-nav');
mb&&mb.addEventListener('click',function(){var o=nav.classList.toggle('open');mb.setAttribute('aria-expanded',o)});

/* image fallback */
function fb(img){img.addEventListener('error',function(){var d=document.createElement('div');d.className='img-ph';d.textContent='A.A.News';if(img.parentNode)img.parentNode.replaceChild(d,img)},{once:true})}
function wireImages(r){$$('img[data-fallback]',r).forEach(function(i){if(i.complete&&!i.naturalWidth){var d=document.createElement('div');d.className='img-ph';d.textContent='A.A.News';i.parentNode&&i.parentNode.replaceChild(d,i)}else fb(i)})}wireImages();

/* bookmarks */
function saved(){return store.get('aa_saved',[])}
function paintSaves(r){var s=saved();$$('[data-save]',r).forEach(function(b){var on=s.indexOf(+b.dataset.save)>-1;b.setAttribute('aria-pressed',on);var l=$('.save-label',b);if(l)l.textContent=on?'🔖 Saved':'🔖 Save';b.title=on?'Remove from saved':'Save for later'});var c=$('#saved-count');if(c){c.hidden=!s.length;c.textContent=s.length}}
document.addEventListener('click',function(e){var b=e.target.closest('[data-save]');if(!b)return;e.preventDefault();var id=+b.dataset.save,s=saved(),i=s.indexOf(id);if(i>-1){s.splice(i,1);toast('Removed from saved')}else{s.unshift(id);toast('Saved for later')}store.set('aa_saved',s.slice(0,100));paintSaves();if($('#local-grid')&&$('#local-grid').dataset.mode==='saved'&&i>-1){var c=b.closest('.card');c&&c.remove();emptyCheck()}});
paintSaves();

/* reading history (only article pages) */
var art=$('#article');
if(art){var h=store.get('aa_history',[]).filter(function(x){return x!==+art.dataset.id});h.unshift(+art.dataset.id);store.set('aa_history',h.slice(0,50));
 var fs=+(localStorage.getItem('aa_fs')||0);function applyFs(){document.documentElement.style.setProperty('--fs',[0.9,1,1.15,1.3,1.5][fs+1])}applyFs();
 $$('[data-fs]').forEach(function(b){b.addEventListener('click',function(){fs=Math.max(-1,Math.min(3,fs+ +b.dataset.fs));try{localStorage.setItem('aa_fs',fs)}catch(e){}applyFs()})});
 var url=location.origin+location.pathname,sb=$('#share-btn');
 if(!navigator.share&&sb)sb.hidden=true;sb&&sb.addEventListener('click',function(){navigator.share({title:sb.dataset.title,url:url}).catch(function(){})});
 $('#copy-btn').addEventListener('click',function(){if(navigator.clipboard)navigator.clipboard.writeText(url).then(function(){toast('Link copied')},function(){toast(url)});else toast(url)})}

/* saved / history page */
var lg=$('#local-grid');
function emptyCheck(){if(!lg)return;var n=$$('.card',lg).length;$('#local-empty').hidden=n>0;$('#local-clear').hidden=n===0}
if(lg){var key=lg.dataset.mode==='saved'?'aa_saved':'aa_history',ids=store.get(key,[]);
 if(!ids.length){emptyCheck()}else{fetch('/fragment/cards?ids='+ids.join(',')).then(function(r){return r.text()}).then(function(t){lg.innerHTML=t;wireImages(lg);paintSaves(lg);emptyCheck()}).catch(function(){lg.innerHTML='<p class="muted">Could not load right now. Check your connection.</p>'})}
 $('#local-clear').addEventListener('click',function(){store.set(key,[]);lg.innerHTML='';paintSaves();emptyCheck()})}

/* load more on home */
var lm=$('#load-more');
if(lm){var grid=$('#latest-grid');lm.addEventListener('click',function(){load()});
 var busy=false;function load(){if(busy)return;busy=true;lm.disabled=true;lm.textContent='Loading…';var p=+lm.dataset.page;
  fetch('/fragment/cards?page='+p+'&exclude='+encodeURIComponent(grid.dataset.exclude||'')).then(function(r){var more=r.headers.get('X-Has-More')==='1';return r.text().then(function(t){return[t,more]})}).then(function(a){var d=document.createElement('div');d.innerHTML=a[0];while(d.firstChild)grid.appendChild(d.firstChild);wireImages(grid);paintSaves(grid);lm.dataset.page=p+1;lm.disabled=false;lm.textContent='Load more';if(!a[1])lm.hidden=true;busy=false})
  .catch(function(){lm.disabled=false;lm.textContent='Retry';busy=false;toast("Couldn't load more. Check your connection.")})}
 if('IntersectionObserver' in window){new IntersectionObserver(function(en){if(en[0].isIntersecting&&!lm.hidden&&!busy)load()},{rootMargin:'400px'}).observe(lm)}}

/* debounced live search suggestions */
var q=$('#q'),sg=$('#suggest'),tm,ctl;
if(q&&sg){q.addEventListener('input',function(){clearTimeout(tm);var v=q.value.trim();if(v.length<2){sg.hidden=true;return}tm=setTimeout(function(){ctl&&ctl.abort();ctl=window.AbortController?new AbortController():null;
 fetch('/api/suggest?q='+encodeURIComponent(v),ctl?{signal:ctl.signal}:{}).then(function(r){return r.json()}).then(function(items){sg.innerHTML='';if(!items.length){sg.hidden=true;return}items.forEach(function(i){var li=document.createElement('li'),a=document.createElement('a');a.href=i.href;a.textContent=i.title;li.appendChild(a);sg.appendChild(li)});sg.hidden=false}).catch(function(){})},250)});
 document.addEventListener('click',function(e){if(!e.target.closest('#search-form'))sg.hidden=true});q.addEventListener('keydown',function(e){if(e.key==='Escape')sg.hidden=true})}

/* confirm for admin forms (no inline handlers: CSP) */
document.addEventListener('submit',function(e){var m=e.target.dataset&&e.target.dataset.confirm;if(m&&!confirm(m))e.preventDefault()});

/* offline indicator */
function net(){var b=$('#offline-bar');if(b)b.hidden=navigator.onLine}window.addEventListener('online',net);window.addEventListener('offline',net);net();

/* PWA: service worker + install */
var dp;window.addEventListener('beforeinstallprompt',function(e){e.preventDefault();dp=e;var b=$('#install-btn');if(b)b.hidden=false});
$('#install-btn')&&$('#install-btn').addEventListener('click',function(){if(!dp){toast('Use your browser menu: Add to Home screen');return}dp.prompt();dp.userChoice.finally(function(){dp=null;$('#install-btn').hidden=true})});
window.addEventListener('appinstalled',function(){var b=$('#install-btn');if(b)b.hidden=true});
if('serviceWorker' in navigator&&(location.protocol==='https:'||location.hostname==='localhost')){window.addEventListener('load',function(){
 navigator.serviceWorker.register('/sw.js',{scope:'/'}).then(function(reg){
  function ask(w){var bar=$('#update-bar');if(!bar||!w)return;bar.hidden=false;$('#update-btn').onclick=function(){w.postMessage('SKIP_WAITING')}}
  if(reg.waiting&&navigator.serviceWorker.controller)ask(reg.waiting);
  reg.addEventListener('updatefound',function(){var w=reg.installing;w&&w.addEventListener('statechange',function(){if(w.state==='installed'&&navigator.serviceWorker.controller)ask(w)})})}).catch(function(){});
 var rl;navigator.serviceWorker.addEventListener('controllerchange',function(){if(rl)return;rl=true;location.reload()})})}
})();
