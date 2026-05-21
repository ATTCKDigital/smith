import { something } from "./util";
import path from "path";

export function add(a, b) {
  return a + b;
}

export const multiply = (a, b) => a * b;

export class Greeter {
  constructor(name) {
    this.name = name;
  }
  greet() {
    return "hello " + this.name;
  }
}

function helper() {
  return path.join("a", "b");
}

export { helper };
