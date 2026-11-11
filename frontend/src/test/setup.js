import "@testing-library/jest-dom/vitest";

// Node >= 25 ships a global `localStorage`/`sessionStorage` getter that yields
// `undefined` unless `--localstorage-file` is set, and vitest's jsdom environment
// will not overwrite an existing global. Rebind them to jsdom's Web Storage
// (vitest exposes the JSDOM instance as `globalThis.jsdom`) so the suite behaves
// the same regardless of the Node version running it.
const jsdomWindow = globalThis.jsdom?.window;
for (const key of ["localStorage", "sessionStorage"]) {
  if (globalThis[key] === undefined && jsdomWindow?.[key] !== undefined) {
    Object.defineProperty(globalThis, key, {
      value: jsdomWindow[key],
      configurable: true,
      writable: true,
    });
  }
}

if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

if (!window.matchMedia) {
  window.matchMedia = () => ({
    matches: false,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  });
}
