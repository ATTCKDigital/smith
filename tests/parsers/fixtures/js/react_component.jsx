import React from "react";

export function Button(props) {
  return <button onClick={props.onClick}>{props.label}</button>;
}

export const Card = ({ title, children }) => (
  <div className="card">
    <h2>{title}</h2>
    {children}
  </div>
);

export default function App() {
  return (
    <div>
      <Button label="Click me" />
      <Card title="Hello">World</Card>
    </div>
  );
}
