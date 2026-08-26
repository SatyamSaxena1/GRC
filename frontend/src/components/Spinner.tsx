/** A small inline CSS spinner — no library, just a rotating border. Used anywhere
 * something is actively happening (model extraction, polling) so the page has
 * visible signs of life instead of a static badge that looks the same whether
 * work is in progress or finished. */
export function Spinner({ size = 14 }: { size?: number }) {
  return (
    <span
      className="spinner"
      style={{ width: size, height: size, borderWidth: Math.max(2, size / 7) }}
      aria-hidden="true"
    />
  );
}
