const { chromium } = require('playwright');

async function checkPage(browser, url) {
  const page = await browser.newPage();
  const consoleMessages = [];
  const pageErrors = [];
  page.on('console', (msg) => {
    consoleMessages.push({ type: msg.type(), text: msg.text() });
  });
  page.on('pageerror', (err) => {
    pageErrors.push(String(err));
  });

  let status = null;
  try {
    const response = await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
    status = response ? response.status() : null;
    await page.waitForTimeout(1500);
    const title = await page.title();
    return {
      url,
      status,
      title,
      pageErrors,
      severeConsole: consoleMessages.filter((item) => item.type === 'error'),
    };
  } finally {
    await page.close();
  }
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const results = [];
    results.push(await checkPage(browser, 'http://localhost:3002/'));
    results.push(await checkPage(browser, 'http://localhost:3002/chat/new'));
    console.log(JSON.stringify(results, null, 2));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
