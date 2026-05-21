export interface User {
  id: number;
  name: string;
  email?: string;
}

export type Result<T> = { ok: true; value: T } | { ok: false; error: string };

export function getUser(id: number): User {
  return { id, name: "test" };
}

export const formatUser = (u: User): string => `${u.name} <${u.email ?? ""}>`;
