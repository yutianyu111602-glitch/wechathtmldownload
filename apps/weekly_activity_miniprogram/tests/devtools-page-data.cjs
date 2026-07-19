function withTimeout(promise, timeoutMs, label) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} timed out after ${timeoutMs}ms`)), timeoutMs);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

async function readPageDataWithFallback(miniProgram, page, options = {}) {
  const label = options.label || "page data";
  const pageDataTimeoutMs = Number(options.pageDataTimeoutMs || 8000);
  const evaluateTimeoutMs = Number(options.evaluateTimeoutMs || 25000);

  try {
    return await withTimeout(page.data(), pageDataTimeoutMs, `${label} page.data`);
  } catch (error) {
    const payload = await withTimeout(miniProgram.evaluate(() => {
      const pages = getCurrentPages();
      const current = pages[pages.length - 1];
      return {
        route: current && current.route,
        data: JSON.parse(JSON.stringify((current && current.data) || {})),
      };
    }), evaluateTimeoutMs, `${label} evaluate fallback`);
    const data = payload && payload.data ? payload.data : {};
    Object.defineProperty(data, "__dataReadFallback", {
      value: {
        route: payload && payload.route ? payload.route : "",
        reason: error && error.message ? error.message : String(error),
      },
      enumerable: false,
    });
    return data;
  }
}

module.exports = {
  readPageDataWithFallback,
};
