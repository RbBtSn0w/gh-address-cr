const menuButton = document.querySelector('.menu-button');
const mobileNav = document.querySelector('.mobile-nav');
const locale = document.documentElement.lang.toLowerCase();

menuButton?.addEventListener('click', () => {
  if (!mobileNav) return;
  const isOpen = mobileNav.classList.toggle('open');
  menuButton.setAttribute('aria-expanded', String(isOpen));
});

mobileNav?.querySelectorAll('a').forEach((link) => {
  link.addEventListener('click', () => {
    mobileNav.classList.remove('open');
    menuButton?.setAttribute('aria-expanded', 'false');
  });
});

const year = document.querySelector('#year');
if (year) year.textContent = new Date().getFullYear();

document.querySelectorAll('.copy-button').forEach((button) => button.addEventListener('click', async (event) => {
  const command = event.currentTarget.dataset.command;
  if (!command) return;
  const defaultLabel = event.currentTarget.dataset.copyLabel || 'Copy';
  const successLabel = event.currentTarget.dataset.copiedLabel || 'Copied';
  const errorLabel = event.currentTarget.dataset.errorLabel || (locale.startsWith('zh') ? '请选中文本' : 'Select text');
  try {
    await navigator.clipboard.writeText(command);
    event.currentTarget.textContent = successLabel;
    setTimeout(() => { event.currentTarget.textContent = defaultLabel; }, 1600);
  } catch {
    event.currentTarget.textContent = errorLabel;
  }
}));
