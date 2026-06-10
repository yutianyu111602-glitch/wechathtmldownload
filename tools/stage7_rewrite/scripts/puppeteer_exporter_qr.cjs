const puppeteer = require('puppeteer');
const fs = require('fs');

const DASHBOARD_URL = 'http://127.0.0.1:3000/dashboard/account';
const MODE = process.argv[2] || 'qr';  // qr | poll | full

async function captureQR(page) {
    await page.goto(DASHBOARD_URL, { waitUntil: 'networkidle2', timeout: 20000 });
    await new Promise(r => setTimeout(r, 3000));
    
    // Click login button
    await page.evaluate(() => {
        for (const b of document.querySelectorAll('button')) {
            if (b.innerText.includes('登录')) { b.click(); return; }
        }
    });
    
    // Wait for QR image
    try {
        await page.waitForSelector('img[src*="getqrcode"]', { timeout: 10000 });
    } catch(e) {
        console.log(JSON.stringify({ ok: false, error: 'QR image not found: ' + e.message }));
        return null;
    }
    
    await new Promise(r => setTimeout(r, 2000));
    
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
        const outPath = process.env.QR_OUT || '/app/.data/current-login-qr.png';
        fs.writeFileSync(outPath, Buffer.from(qrData.data, 'base64'));
        return { ok: true, w: qrData.w, h: qrData.h, path: outPath };
    }
    return null;
}

async function pollScan(page, timeoutSec) {
    const deadline = Date.now() + timeoutSec * 1000;
    const pollInterval = 3000;
    
    while (Date.now() < deadline) {
        const status = await page.evaluate(async () => {
            try {
                const r = await fetch('/api/web/login/scan');
                return await r.json();
            } catch(e) {
                return { error: e.message };
            }
        });
        
        const scanStatus = status.status;
        if (scanStatus === 1) {
            // Confirmed! Do bizlogin
            const loginResult = await page.evaluate(async () => {
                try {
                    const r = await fetch('/api/web/login/bizlogin', { method: 'POST' });
                    return await r.json();
                } catch(e) {
                    return { error: e.message };
                }
            });
            return { scanned: true, status: scanStatus, login: loginResult };
        } else if (scanStatus === 2 || scanStatus === 3) {
            return { scanned: false, expired: true, status: scanStatus };
        } else if (scanStatus === 5) {
            return { scanned: false, error: 'account_email_not_bound', status: scanStatus };
        }
        
        await new Promise(r => setTimeout(r, pollInterval));
    }
    
    return { scanned: false, timeout: true };
}

(async () => {
    const browser = await puppeteer.launch({ headless: true, args: ['--no-sandbox','--disable-setuid-sandbox'] });
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 800 });
    
    try {
        if (MODE === 'qr') {
            const result = await captureQR(page);
            console.log(JSON.stringify(result || { ok: false, error: 'capture failed' }));
        } else if (MODE === 'full') {
            const qrResult = await captureQR(page);
            if (!qrResult || !qrResult.ok) {
                console.log(JSON.stringify(qrResult || { ok: false, error: 'capture failed' }));
                await browser.close();
                process.exit(1);
            }
            console.log(JSON.stringify({ phase: 'qr_ready', ...qrResult }));
            
            const timeoutSec = parseInt(process.env.POLL_TIMEOUT || '180');
            const scanResult = await pollScan(page, timeoutSec);
            console.log(JSON.stringify({ phase: 'scan_complete', ...scanResult }));
        }
    } finally {
        await browser.close();
    }
})().catch(e => {
    console.log(JSON.stringify({ ok: false, error: e.message }));
    process.exit(1);
});
