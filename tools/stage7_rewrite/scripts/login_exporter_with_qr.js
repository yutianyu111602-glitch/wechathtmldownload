const puppeteer = require('puppeteer');
const fs = require('fs');

(async () => {
    const browser = await puppeteer.launch({ headless: true, args: ['--no-sandbox','--disable-setuid-sandbox'] });
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 800 });
    
    // Navigate to account page
    await page.goto('http://127.0.0.1:3000/dashboard/account', { waitUntil: 'networkidle2', timeout: 20000 });
    await new Promise(r => setTimeout(r, 2000));
    
    // Check if already logged in
    const alreadyLoggedIn = await page.evaluate(() => {
        // Check for elements that indicate login state
        const loginBtn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('登录'));
        const accountTable = document.querySelector('table');
        const noData = document.body.innerText.includes('暂无数据');
        return { hasLoginBtn: !!loginBtn, hasAccountTable: !!accountTable, noData };
    });
    
    console.log(JSON.stringify({ alreadyLoggedIn }));
    
    if (!alreadyLoggedIn.hasLoginBtn) {
        console.log(JSON.stringify({ status: 'already_logged_in', suggestion: 'try adding accounts' }));
        await browser.close();
        return;
    }
    
    // Click login button
    await page.evaluate(() => {
        for (const b of document.querySelectorAll('button')) {
            if (b.innerText.includes('登录')) { b.click(); return; }
        }
    });
    
    // Wait for QR image
    let qrFound = false;
    try {
        await page.waitForSelector('img[src*="getqrcode"]', { timeout: 10000 });
        qrFound = true;
    } catch(e) {
        console.log(JSON.stringify({ error: 'no_qr_selector', msg: e.message }));
    }
    
    if (qrFound) {
        await new Promise(r => setTimeout(r, 2000));
        
        // Capture QR
        const qrData = await page.evaluate(async () => {
            const img = document.querySelector('img[src*="getqrcode"]');
            if (!img) return null;
            const canvas = document.createElement('canvas');
            canvas.width = img.naturalWidth || img.width;
            canvas.height = img.naturalHeight || img.height;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0);
            return { data: canvas.toDataURL('image/png').split(',')[1], w: canvas.width, h: canvas.height };
        });
        
        if (qrData && qrData.data) {
            fs.writeFileSync('/app/.data/current-login-qr.png', Buffer.from(qrData.data, 'base64'));
            console.log(JSON.stringify({ ok: true, status: 'qr_ready_waiting_scan', w: qrData.w, h: qrData.h, path: '/app/.data/current-login-qr.png' }));
        }
        
        // Wait for scan (up to 60 seconds)
        try {
            await page.waitForFunction(() => {
                return !document.querySelector('img[src*="getqrcode"]') || 
                       document.body.innerText.includes('已登录') ||
                       document.querySelector('table');
            }, { timeout: 60000 });
            
            console.log(JSON.stringify({ status: 'scan_detected_or_timeout', loggedIn: !document.querySelector('img[src*="getqrcode"]') }));
        } catch(e) {
            console.log(JSON.stringify({ status: 'scan_wait_timeout' }));
        }
    }
    
    await browser.close();
})().catch(e => {
    console.log(JSON.stringify({ ok: false, error: e.message }));
    process.exit(1);
});
