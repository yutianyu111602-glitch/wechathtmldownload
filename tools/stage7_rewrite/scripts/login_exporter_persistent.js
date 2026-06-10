const puppeteer = require('puppeteer');
const fs = require('fs');

(async () => {
    console.log(JSON.stringify({step: 'launch'}));
    const browser = await puppeteer.launch({ headless: true, args: ['--no-sandbox','--disable-setuid-sandbox'] });
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 800 });
    
    // Go to account page
    await page.goto('http://127.0.0.1:3000/dashboard/account', { waitUntil: 'networkidle2', timeout: 20000 });
    await new Promise(r => setTimeout(r, 3000));
    
    // Check if already logged in (no login button = logged in)
    const hasLoginBtn = await page.evaluate(() => {
        const btns = Array.from(document.querySelectorAll('button'));
        return btns.some(b => b.innerText.includes('登录公众号'));
    });
    
    if (!hasLoginBtn) {
        console.log(JSON.stringify({status: 'already_logged_in', msg: 'No login button found'}));
        await browser.close();
        return;
    }
    
    // Click login
    console.log(JSON.stringify({step: 'click_login'}));
    await page.evaluate(() => {
        for (const b of document.querySelectorAll('button')) {
            if (b.innerText.includes('登录公众号')) { b.click(); return; }
        }
    });
    await new Promise(r => setTimeout(r, 1000));
    
    // Click the dialog button to start QR flow
    const dialogBtn = await page.evaluate(() => {
        const dialog = document.querySelector('[role="dialog"], .el-dialog, .modal');
        if (dialog) {
            const btn = dialog.querySelector('button');
            if (btn) { btn.click(); return 'clicked'; }
        }
        return 'no_dialog';
    });
    console.log(JSON.stringify({step: 'dialog_btn', result: dialogBtn}));
    await new Promise(r => setTimeout(r, 3000));
    
    // Look for QR image
    const qrFound = await page.evaluate(() => {
        const img = document.querySelector('img');
        if (img) return {src: img.src.substring(0, 100), w: img.width, h: img.height};
        const canvas = document.querySelector('canvas');
        if (canvas) return {canvas: true, w: canvas.width, h: canvas.height};
        return null;
    });
    console.log(JSON.stringify({step: 'qr_check', found: qrFound}));
    
    if (qrFound && (qrFound.src || qrFound.canvas)) {
        // Capture QR
        let qrData;
        if (qrFound.canvas) {
            qrData = await page.evaluate(() => {
                const c = document.querySelector('canvas');
                return {data: c.toDataURL('image/png').split(',')[1], w: c.width, h: c.height};
            });
        } else {
            qrData = await page.evaluate(() => {
                const img = document.querySelector('img');
                const c = document.createElement('canvas');
                c.width = img.naturalWidth || img.width;
                c.height = img.naturalHeight || img.height;
                c.getContext('2d').drawImage(img, 0, 0);
                return {data: c.toDataURL('image/png').split(',')[1], w: c.width, h: c.height};
            });
        }
        
        if (qrData && qrData.data) {
            fs.writeFileSync('/app/.data/current-login-qr.png', Buffer.from(qrData.data, 'base64'));
            console.log(JSON.stringify({status: 'qr_ready', w: qrData.w, h: qrData.h, path: '/app/.data/current-login-qr.png'}));
        }
        
        // Wait for scan (up to 120 seconds)
        console.log(JSON.stringify({step: 'waiting_scan', max_wait: 120}));
        const startTime = Date.now();
        let loggedIn = false;
        
        while (Date.now() - startTime < 120000) {
            await new Promise(r => setTimeout(r, 3000));
            
            loggedIn = await page.evaluate(() => {
                // Check if login button disappeared
                const hasLogin = Array.from(document.querySelectorAll('button')).some(b => b.innerText.includes('登录公众号'));
                const hasTable = !!document.querySelector('table');
                const hasAccount = !document.body.innerText.includes('暂无数据');
                return !hasLogin || hasTable || hasAccount;
            });
            
            if (loggedIn) {
                console.log(JSON.stringify({status: 'scan_detected', elapsed_sec: Math.floor((Date.now()-startTime)/1000)}));
                break;
            }
        }
        
        if (!loggedIn) {
            console.log(JSON.stringify({status: 'scan_timeout', elapsed_sec: 120}));
        }
    }
    
    // Final state check
    const finalState = await page.evaluate(() => ({
        hasLoginBtn: Array.from(document.querySelectorAll('button')).some(b => b.innerText.includes('登录公众号')),
        bodyText: document.body.innerText.substring(0, 200),
    }));
    console.log(JSON.stringify({step: 'final', state: finalState}));
    
    await browser.close();
})().catch(e => {
    console.log(JSON.stringify({ok: false, error: e.message}));
    process.exit(1);
});
