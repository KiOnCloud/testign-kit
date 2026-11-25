// How a phone-width case is checked: a real device (the tester's) or Chrome's emulation, which the
// agent may run in a 390 px frame. A pc case has no method.

export const MOBILE_METHODS = ['device', 'emulation'];

/** How a row is checked on a phone: none on pc rows; a real device unless the row says emulation. */
export function mobileMethod(viewport, method) {
  if (viewport !== 'mobile') return null;
  return MOBILE_METHODS.includes(method) ? method : 'device';
}
