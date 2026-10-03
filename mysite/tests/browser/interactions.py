from playwright.sync_api import sync_playwright
B='http://localhost:5055'; out=[]
def ok(n,c): print('PASS' if c else 'FAIL',n,flush=True)
with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={'width':390,'height':844}); pg=ctx.new_page()
    pg.goto(B+'/'); pg.wait_for_timeout(400)
    ok('saved badge hidden at 0', not pg.locator('#saved-count').is_visible())
    # theme persists
    pg.click('#theme-btn'); ok('dark applied', pg.evaluate("document.documentElement.dataset.theme")=='dark')
    pg.reload(); ok('dark persists after reload', pg.evaluate("document.documentElement.dataset.theme")=='dark')
    pg.click('#theme-btn')
    # bookmark from card
    pg.locator('.card .save-btn').first.click(); pg.wait_for_timeout(200)
    ok('bookmark stored', len(pg.evaluate("JSON.parse(localStorage.aa_saved)"))==1)
    ok('badge shows 1', pg.locator('#saved-count').inner_text()=='1')
    pg.goto(B+'/saved'); pg.wait_for_timeout(800)
    ok('saved page renders card', pg.locator('#local-grid .card').count()==1)
    pg.locator('#local-grid .save-btn').first.click(); pg.wait_for_timeout(200)
    ok('remove from saved page', pg.locator('#local-grid .card').count()==0 and pg.locator('#local-empty').is_visible())
    # article page: history, font size, copy
    pg.goto(B+'/'); href=pg.evaluate("document.querySelectorAll('.card-title a')[3].getAttribute('href')"); pg.goto(B+href); pg.wait_for_timeout(300)
    ok('history recorded', len(pg.evaluate("JSON.parse(localStorage.aa_history)"))==1)
    f0=pg.evaluate("getComputedStyle(document.querySelector('#a-body p, #a-body')).fontSize")
    pg.click('[data-fs="1"]'); f1=pg.evaluate("getComputedStyle(document.querySelector('#a-body p, #a-body')).fontSize")
    ok(f'font size control {f0}->{f1}', float(f1[:-2])>float(f0[:-2]))
    pg.click('.tools [data-save]'); ok('article save toggles', pg.get_attribute('.tools [data-save]','aria-pressed')=='true')
    pg.goto(B+'/history'); pg.wait_for_timeout(800); ok('history page lists it', pg.locator('#local-grid .card').count()==1)
    # load more
    pg.goto(B+'/'); n0=pg.locator('#latest-grid .card').count(); pg.evaluate("document.querySelector('#load-more').scrollIntoView()"); pg.wait_for_timeout(1200)
    n1=pg.locator('#latest-grid .card').count(); ok(f'load more {n0}->{n1}', n1>n0)
    # suggestions (debounced)
    pg.fill('#q','india'); pg.wait_for_timeout(700); ok('live suggestions shown', pg.locator('#suggest li').count()>0)
    pg.press('#q','Enter'); pg.wait_for_timeout(500); ok('search results page', '/search?q=india' in pg.url)
    # filters + pagination preserve
    pg.goto(B+'/search?category=sports&sort=new'); pg.wait_for_timeout(300)
    nxt=pg.locator('a[rel=next]'); 
    if nxt.count(): ok('pager keeps filters', 'category=sports' in nxt.get_attribute('href'))
    pg.click('text=Clear'); ok('clear resets', pg.url.endswith('/search'))
    # service worker + offline
    pg.goto(B+'/'); pg.wait_for_timeout(1500)
    ok('service worker registered', pg.evaluate("navigator.serviceWorker.getRegistration().then(r=>!!r)"))
    pg.reload(); pg.wait_for_timeout(1000)
    cached=pg.evaluate("caches.keys()"); ok('caches created '+str(cached), len(cached)>=1)
    pg.goto(B+'/about'); pg.wait_for_timeout(700)
    ctx.set_offline(True)
    pg.goto(B+'/about'); ok('visited page works offline', 'About Us' in pg.inner_text('h1'))
    pg.goto(B+'/section/science'); ok('unvisited page shows offline fallback', "offline" in pg.inner_text('h1').lower())
    try:
        pg.goto(B+'/admin'); ok('admin NOT served from cache offline', False)
    except Exception as e:
        ok('admin NOT served from cache offline (network error, nothing cached)', 'ERR_INTERNET_DISCONNECTED' in str(e))
    ctx.set_offline(False); pg.goto(B+'/')
    mf=pg.evaluate("fetch('/manifest.webmanifest').then(r=>r.headers.get('content-type'))"); ok('manifest mime '+mf, 'manifest' in mf)
    # admin pages not cached
    ctx.close(); b.close()
for r in out: print(*r)
