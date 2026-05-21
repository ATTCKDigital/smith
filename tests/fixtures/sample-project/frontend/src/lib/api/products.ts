export async function listProducts(): Promise<
  Array<{ id: number; name: string }>
> {
  const res = await fetch("/api/v1/products");
  return res.json();
}

export async function createProduct(name: string): Promise<{ id: number }> {
  const res = await fetch("/api/v1/products", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
  return res.json();
}

export async function getProduct(
  id: number,
): Promise<{ id: number; name: string }> {
  const res = await fetch(`/api/v1/products/${id}`);
  return res.json();
}
