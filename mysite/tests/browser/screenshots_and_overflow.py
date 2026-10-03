from playwright.sync_api import sync_playwright
B='http://localhost:5055'
res=[]
with sync_playwright() as p:
    b=p.chromium.launch()
    for name,w,h,dark in [('mobile',390,844,False),('mobile-dark',390,844,True),('tablet',768,1024,False),('desktop',1280,800,False),('desktop-dark',1280,800,True)]:
        ctx=b.new_context(viewport={'width':w,'height':h},color_scheme='dark' if dark else 'light',is_mobile=(w<500),has_touch=(w<500))
        pg=ctx.new_page(); errs=[]
        pg.on('pageerror',lambda e:errs.append(str(e)))
        pg.on('console',lambda m:errs.append(m.text) if m.type=='error' and 'net::' not in m.text and 'Failed to load resource' not in m.text else None)
        for path,tag in [('/','home'),('/search?q=news','search'),('/section/sports','section')]:
            pg.goto(B+path,wait_until='load'); pg.wait_for_timeout(300)
            ov=pg.evaluate('document.documentElement.scrollWidth - document.documentElement.clientWidth')
            res.append((name,path,'overflow_px',ov))
            if tag=='home' or name in('mobile','desktop-dark'): pg.screenshot(path=f'/tmp/shots/{name}-{tag}.png',full_page=False)
        # article
        href=pg.evaluate("document.querySelector('.card-title a').getAttribute('href')")
        pg.goto(B+href,wait_until='load'); pg.wait_for_timeout(300)
        res.append((name,'article','overflow_px',pg.evaluate('document.documentElement.scrollWidth - document.documentElement.clientWidth')))
        if name in('mobile','desktop'): pg.screenshot(path=f'/tmp/shots/{name}-article.png')
        res.append((name,'js_errors',errs))
        ctx.close()
    b.close()
for r in res: print(r)
