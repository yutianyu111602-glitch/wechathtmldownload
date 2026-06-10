const puppeteer = require('puppeteer');
const fs = require('fs');

(async () => {
    const browser = await puppeteer.launch({ headless: true, args: ['--no-sandbox','--disable-setuid-sandbox'] });
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 800 });
    
    await page.goto('http://127.0.0.1:3000/dashboard/account', { waitUntil: 'networkidle2', timeout: 20000 });
    await new Promise(r => setTimeout(r, 3000));
    
    // Click login button
    await page.evaluate(() => {
        for (const b of document.querySelectorAll('button')) {
            if (b.innerText.includes('登录')) { b.click(); return; }
        }
    });
    
    // Wait for QR image to appear
    try {
        await page.waitForSelector('img[src*="getqrcode"]', { timeout: 10000 });
    } catch(e) {
        console.log('QR image selector not found: ' + e.message);
        await page.screenshot({ path: '/app/.data/login-debug.png' });
        await browser.close();
        process.exit(1);
    }
    
    await new Promise(r => setTimeout(r, 2000));
    
    // Get QR image via canvas
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
        console.log(JSON.stringify({ ok: true, w: qrData.w, h: qrData.h, size: qrData.data.length, path: '/app/.data/current-login-qr.png' }));
    } else {
        console.log(JSON.stringify({ ok: false, error: 'no qr data extracted' }));
    }
    
    await browser.close();
})().catch(e => {
    console.log(JSON.stringify({ ok: false, error: e.message }));
    process.exit(1);
});
