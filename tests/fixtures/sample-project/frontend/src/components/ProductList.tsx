import React from "react";

export interface ProductListProps {
  products: Array<{ id: number; name: string }>;
}

export function ProductList({ products }: ProductListProps) {
  return (
    <ul>
      {products.map((p) => (
        <li key={p.id}>{p.name}</li>
      ))}
    </ul>
  );
}

export default ProductList;
