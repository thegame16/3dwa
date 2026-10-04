const STORAGE_KEY = 'forma-inventory-v1';
const COLORS = ['peach', 'sage', 'lavender', 'sand', 'blue', 'rose'];
const SYMBOLS = ['◒', '◈', '▧', '◯', '✳', '▱'];
let products = [];
let currency = 'USD';
let activeSaleId = null;
let sortNewestFirst = true;
let photoData = '';
let currentUser = null;
let saveQueue = Promise.resolve();
let isCreatingAccount = false;
let audioContext = null;
let soundsEnabled = localStorage.getItem('edwa-sounds-enabled') !== 'false';
const $ = (selector) => document.querySelector(selector);

function readProducts() {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
    return Array.isArray(value) ? value.filter((item) => item && typeof item.id === 'string' && Number.isFinite(item.price) && Number.isFinite(item.quantity)) : [];
  } catch { return []; }
}
function save() {
  saveQueue = saveQueue.then(async () => {
    if (!currentUser) return;
    const response = await fetch('/api/inventory', { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin', body: JSON.stringify({ products, currency }) });
    if (!response.ok) throw new Error('Inventory could not be saved. Check your connection and sign in again if needed.');
  }).catch((error) => toast(error.message || 'Inventory could not be saved.'));
}
function money(amount) {
  try { return new Intl.NumberFormat(undefined, { style: 'currency', currency, maximumFractionDigits: 2 }).format(amount); }
  catch { return `${currency} ${Number(amount).toFixed(2)}`; }
}
function currencySymbol() {
  try { return new Intl.NumberFormat(undefined, { style: 'currency', currency }).formatToParts(0).find((part) => part.type === 'currency')?.value || currency; }
  catch { return currency; }
}
function unlockAudio() {
  try {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return;
    audioContext ||= new AudioContextClass();
    if (audioContext.state === 'suspended') audioContext.resume();
  } catch { /* Audio may be unavailable in this browser. */ }
}
function playInventorySound(direction) {
  if (!soundsEnabled) return;
  try {
    unlockAudio();
    if (!audioContext) return;
    const now = audioContext.currentTime;
    const notes = direction === 'up' ? [523.25, 783.99, 1046.5] : [659.25, 440];
    notes.forEach((frequency, index) => {
      const start = now + index * (direction === 'up' ? 0.075 : 0.11);
      const oscillator = audioContext.createOscillator();
      const gain = audioContext.createGain();
      oscillator.type = direction === 'up' ? 'sine' : 'triangle';
      oscillator.frequency.setValueAtTime(frequency, start);
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.035, start + 0.012);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + (direction === 'up' ? 0.19 : 0.22));
      oscillator.connect(gain); gain.connect(audioContext.destination);
      oscillator.start(start); oscillator.stop(start + 0.23);
    });
  } catch { /* Inventory updates should still work when audio is unavailable. */ }
}
function escapeHTML(value = '') {
  return String(value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
}
function stockStatus(product) {
  if (product.quantity <= 0) return ['out', 'Out of stock'];
  if (product.quantity <= 5) return ['low', 'Low stock'];
  return ['in', 'In stock'];
}
function render() {
  const query = $('#search').value.trim().toLowerCase();
  const filter = $('#stock-filter').value;
  const filtered = products.filter((product) => {
    const matchesText = `${product.name} ${product.category || ''}`.toLowerCase().includes(query);
    const status = stockStatus(product)[0];
    return matchesText && (filter === 'all' || filter === 'low' && status === 'low' || filter === 'out' && status === 'out');
  }).sort((a, b) => sortNewestFirst ? b.createdAt - a.createdAt : a.name.localeCompare(b.name));

  const units = products.reduce((sum, item) => sum + item.quantity, 0);
  const sales = products.reduce((sum, item) => sum + item.sold * item.price, 0);
  const soldCount = products.reduce((sum, item) => sum + item.sold, 0);
  const flagged = products.filter((item) => item.quantity <= 5).length;
  $('#total-units').textContent = units.toLocaleString();
  $('#inventory-value').textContent = money(products.reduce((sum, item) => sum + item.quantity * item.price, 0));
  $('#sales-value').textContent = money(sales);
  $('#units-sold').textContent = `${soldCount.toLocaleString()} ${soldCount === 1 ? 'item' : 'items'}`;
  $('#low-stock').textContent = flagged.toLocaleString();
  $('#product-count').textContent = `${products.length} ${products.length === 1 ? 'product' : 'products'}`;
  $('#nav-count').textContent = products.length;
  $('#heading-count').textContent = products.length;
  $('#showing-count').textContent = `Showing ${filtered.length} of ${products.length} ${products.length === 1 ? 'product' : 'products'}`;
  $('#empty-state').hidden = filtered.length > 0;
  $('#product-grid').innerHTML = filtered.map((product, index) => {
    const [status, label] = stockStatus(product);
    const color = COLORS[index % COLORS.length];
    const media = product.photo
      ? `<img src="${product.photo}" alt="${escapeHTML(product.name)}" />`
      : `<div class="placeholder-art ${color}"><span>${SYMBOLS[index % SYMBOLS.length]}</span><i></i><b></b></div>`;
    return `<article class="product-card" data-id="${escapeHTML(product.id)}">
      <div class="product-visual">${media}<span class="stock-badge ${status}"><i></i>${label}</span><button class="card-menu" data-action="delete" aria-label="Remove ${escapeHTML(product.name)}" title="Remove product">···</button><span class="visual-index">${String(index + 1).padStart(2, '0')}</span></div>
      <div class="product-info"><div class="product-title-row"><div><div class="category-label">${escapeHTML(product.category || 'UNCATEGORIZED')}</div><h3>${escapeHTML(product.name)}</h3></div><div class="product-price">${money(product.price)}<small> / unit</small></div></div>
      <div class="stock-row"><span>Available <b>${product.quantity}</b></span><span class="stock-track"><i class="${status}" style="width:${Math.min(100, product.quantity / Math.max(product.initialQuantity, 10) * 100)}%"></i></span></div>
      <div class="card-footer"><span>${product.sold.toLocaleString()} sold</span><div class="card-actions"><button class="restock-button" data-action="restock" ${product.quantity >= 99999 ? 'disabled' : ''} title="Add stock">＋ Stock</button><button class="sale-button" data-action="sale" ${product.quantity <= 0 ? 'disabled' : ''}>Record sale <span>↗</span></button></div></div></div>
    </article>`;
  }).join('');
}
function toast(message) {
  const node = $('#toast'); node.textContent = message; node.classList.add('show');
  clearTimeout(toast.timer); toast.timer = setTimeout(() => node.classList.remove('show'), 2600);
}
function resetProductForm() {
  $('#product-form').reset(); photoData = ''; $('#photo-preview').innerHTML = '<span class="camera-icon">◎</span>'; $('#photo-preview').classList.remove('has-image');
}
function showProductDialog() { resetProductForm(); $('#price-prefix').textContent = currencySymbol(); $('#product-dialog').showModal(); setTimeout(() => $('#product-name').focus(), 50); }
function openSale(product) {
  activeSaleId = product.id;
  $('#sale-product').innerHTML = `<span class="sale-item-icon">${escapeHTML(product.name.slice(0, 1).toUpperCase())}</span><span><b>${escapeHTML(product.name)}</b><small>${product.quantity} available · ${money(product.price)} each</small></span>`;
  $('#sale-quantity').max = product.quantity; $('#sale-quantity').value = '1';
  $('#sale-note').textContent = `Sale total: ${money(product.price)}`;
  $('#sale-dialog').showModal(); setTimeout(() => $('#sale-quantity').focus(), 50);
}

$('#today').textContent = new Intl.DateTimeFormat(undefined, { weekday: 'short', month: 'short', day: 'numeric' }).format(new Date());
function updateSoundToggle() {
  const toggle = $('#sound-toggle');
  toggle.classList.toggle('muted', !soundsEnabled);
  toggle.setAttribute('aria-pressed', String(soundsEnabled));
  toggle.setAttribute('aria-label', soundsEnabled ? 'Mute sounds' : 'Turn sounds on');
  toggle.title = soundsEnabled ? 'Mute sounds' : 'Turn sounds on';
}
$('#sound-toggle').addEventListener('click', () => {
  soundsEnabled = !soundsEnabled;
  localStorage.setItem('edwa-sounds-enabled', String(soundsEnabled));
  if (soundsEnabled) unlockAudio();
  updateSoundToggle();
  toast(soundsEnabled ? 'Inventory sounds on.' : 'Inventory sounds muted.');
});
updateSoundToggle();

function showAuthError(message) { $('#auth-error').textContent = message; $('#auth-error').hidden = !message; }
function setAuthMode(createAccount) {
  isCreatingAccount = createAccount;
  $('#name-field').hidden = !createAccount;
  $('#auth-name').required = createAccount;
  $('#auth-password').autocomplete = createAccount ? 'new-password' : 'current-password';
  $('#auth-title').innerHTML = createAccount ? 'Make room<br>for more<span>.</span>' : 'Welcome<br>back<span>.</span>';
  $('#auth-description').textContent = createAccount ? 'Create your private workspace for the store.' : 'Sign in to pick up right where you left off.';
  $('#auth-submit').innerHTML = createAccount ? 'Create account <span>↗</span>' : 'Sign in <span>↗</span>';
  $('#auth-switch').innerHTML = createAccount
    ? 'Already have an account? <button type="button" id="auth-toggle">Sign in</button>'
    : 'New to Ɛdwa? <button type="button" id="auth-toggle">Create an account</button>';
  $('#auth-error').hidden = true;
  $('#auth-toggle').addEventListener('click', () => setAuthMode(!isCreatingAccount), { once: true });
}
async function enterWorkspace(user) {
  currentUser = user;
  $('#account-name').textContent = user.name || user.email.split('@')[0];
  $('#account-email').textContent = user.email;
  const initials = (user.name || user.email).trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase();
  $('#account-avatar').textContent = initials;
  $('#profile-avatar').textContent = initials;
  $('#profile-name').textContent = user.name || user.email.split('@')[0];
  $('#profile-role').textContent = 'Store owner';
  const response = await fetch('/api/inventory', { credentials: 'same-origin' });
  if (!response.ok) throw new Error('Could not load your inventory. Please sign in again.');
  const data = await response.json();
  products = Array.isArray(data.products) ? data.products : [];
  currency = data.currency || 'USD';
  const alreadyMigrated = localStorage.getItem('forma-inventory-migrated-v1');
  if (products.length === 0 && !alreadyMigrated) {
    const legacyProducts = readProducts();
    if (legacyProducts.length) products = legacyProducts;
    const legacyCurrency = localStorage.getItem('forma-currency');
    if (legacyCurrency) currency = legacyCurrency;
    localStorage.setItem('forma-inventory-migrated-v1', '1');
    if (legacyProducts.length || legacyCurrency) await persistNow();
  }
  $('#currency-select').value = currency;
  render();
  document.body.classList.add('authenticated');
  $('#auth-screen').hidden = true;
}
async function persistNow() {
  const response = await fetch('/api/inventory', { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin', body: JSON.stringify({ products, currency }) });
  if (!response.ok) throw new Error('Your inventory could not be saved.');
}
async function checkSession() {
  try {
    const response = await fetch('/api/session', { credentials: 'same-origin' });
    const data = await response.json();
    if (data.user) await enterWorkspace(data.user);
    else setAuthMode(false);
  } catch {
    showAuthError('Ɛdwa could not reach the server. Check your connection and refresh the page.');
  }
}
$('#auth-toggle').addEventListener('click', () => setAuthMode(true));
$('#auth-form').addEventListener('submit', async (event) => {
  event.preventDefault(); showAuthError('');
  const submit = $('#auth-submit'); submit.disabled = true; submit.textContent = isCreatingAccount ? 'Creating your account…' : 'Signing you in…';
  try {
    const response = await fetch(isCreatingAccount ? '/api/register' : '/api/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin',
      body: JSON.stringify({ name: $('#auth-name').value.trim(), email: $('#auth-email').value.trim(), password: $('#auth-password').value })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not sign in. Please try again.');
    $('#auth-password').value = '';
    await enterWorkspace(data.user);
  } catch (error) { showAuthError(error.message || 'Could not reach Ɛdwa. Check the server and try again.'); }
  finally { submit.disabled = false; submit.innerHTML = isCreatingAccount ? 'Create account <span>↗</span>' : 'Sign in <span>↗</span>'; }
});
$('#account-menu').addEventListener('click', () => { $('#account-dropdown').hidden = !$('#account-dropdown').hidden; });
document.addEventListener('click', (event) => { if (!event.target.closest('.top-actions')) $('#account-dropdown').hidden = true; });
$('#sign-out').addEventListener('click', async () => {
  await saveQueue;
  await fetch('/api/logout', { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin', body: '{}' });
  currentUser = null; products = []; render(); document.body.classList.remove('authenticated'); $('#account-dropdown').hidden = true; $('#auth-screen').hidden = false; $('#auth-password').value = ''; setAuthMode(false);
});
$('#add-product').addEventListener('click', () => { if (soundsEnabled) unlockAudio(); showProductDialog(); });
$('#empty-add').addEventListener('click', () => { if (soundsEnabled) unlockAudio(); showProductDialog(); });
$('#close-dialog').addEventListener('click', () => $('#product-dialog').close());
$('#cancel-dialog').addEventListener('click', () => $('#product-dialog').close());
$('#search').addEventListener('input', render);
$('#stock-filter').addEventListener('change', render);
$('#sort-button').addEventListener('click', (event) => {
  sortNewestFirst = !sortNewestFirst;
  event.currentTarget.innerHTML = `${sortNewestFirst ? 'Recently added' : 'Name A–Z'} <span>⌄</span>`;
  render();
});
$('#product-photo').addEventListener('change', (event) => {
  const file = event.target.files?.[0]; if (!file) return;
  if (file.size > 5 * 1024 * 1024) { toast('Please choose an image under 5 MB.'); event.target.value = ''; return; }
  const reader = new FileReader();
  reader.onload = () => {
    const image = new Image();
    image.onload = () => {
      const scale = Math.min(1, 1000 / Math.max(image.naturalWidth, image.naturalHeight));
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
      canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
      const context = canvas.getContext('2d');
      context.fillStyle = '#fff'; context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      photoData = canvas.toDataURL('image/jpeg', 0.78);
      $('#photo-preview').innerHTML = `<img src="${photoData}" alt="Product photo preview" />`;
      $('#photo-preview').classList.add('has-image');
    };
    image.onerror = () => toast('That image could not be opened. Please choose another.');
    image.src = reader.result;
  };
  reader.readAsDataURL(file);
});
$('#product-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const name = $('#product-name').value.trim();
  const price = Number($('#product-price').value);
  const quantity = Number($('#product-quantity').value);
  if (!name || !Number.isFinite(price) || price <= 0 || !Number.isInteger(quantity) || quantity < 0) return;
  products.unshift({ id: crypto.randomUUID(), name, price, quantity, initialQuantity: quantity, sold: 0, category: $('#product-category').value.trim(), photo: photoData, createdAt: Date.now() });
  playInventorySound('up'); save(); render(); $('#product-dialog').close(); toast(`${name} added to your inventory.`);
});
$('#product-grid').addEventListener('click', (event) => {
  const button = event.target.closest('[data-action]'); if (!button) return;
  const card = button.closest('[data-id]'); const product = products.find((item) => item.id === card?.dataset.id); if (!product) return;
  if (button.dataset.action === 'sale') { if (soundsEnabled) unlockAudio(); openSale(product); }
  if (button.dataset.action === 'restock') {
    if (soundsEnabled) unlockAudio();
    const addition = Number(prompt(`How many ${product.name} would you like to add?`, '1'));
    if (!Number.isInteger(addition) || addition <= 0) return;
    product.quantity += addition; product.initialQuantity = Math.max(product.initialQuantity, product.quantity); playInventorySound('up'); save(); render(); toast(`${product.name} restocked by ${addition}.`);
  }
  if (button.dataset.action === 'delete' && confirm(`Remove “${product.name}” from your inventory? Sales already recorded will also be removed from your totals.`)) {
    products = products.filter((item) => item.id !== product.id); playInventorySound('down'); save(); render(); toast(`${product.name} removed.`);
  }
});
$('#sale-quantity').addEventListener('input', () => {
  const product = products.find((item) => item.id === activeSaleId); if (!product) return;
  const quantity = Math.max(0, Number($('#sale-quantity').value) || 0);
  $('#sale-note').textContent = `Sale total: ${money(quantity * product.price)}`;
});
$('#close-sale').addEventListener('click', () => $('#sale-dialog').close());
$('#cancel-sale').addEventListener('click', () => $('#sale-dialog').close());
$('#sale-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const product = products.find((item) => item.id === activeSaleId);
  const quantity = Number($('#sale-quantity').value);
  if (!product || !Number.isInteger(quantity) || quantity < 1 || quantity > product.quantity) { toast('Enter a quantity available in stock.'); return; }
  product.quantity -= quantity; product.sold += quantity; playInventorySound('down'); save(); render(); $('#sale-dialog').close(); toast(`${quantity} ${product.name} ${quantity === 1 ? 'sale' : 'sales'} recorded · ${money(quantity * product.price)}.`);
});

$('#settings-button').addEventListener('click', () => { $('#currency-select').value = currency; $('#settings-dialog').showModal(); });
$('#close-settings').addEventListener('click', () => $('#settings-dialog').close());
$('#cancel-settings').addEventListener('click', () => $('#settings-dialog').close());
$('#settings-form').addEventListener('submit', (event) => {
  event.preventDefault(); currency = $('#currency-select').value; $('#price-prefix').textContent = currencySymbol(); save(); render(); $('#settings-dialog').close(); toast('Currency preference saved.');
});
for (const dialog of document.querySelectorAll('dialog')) dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
setAuthMode(false);
checkSession();
