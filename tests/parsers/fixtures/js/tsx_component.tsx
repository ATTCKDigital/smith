import React, { useState } from "react";

interface Props {
  initial: number;
}

export const Counter: React.FC<Props> = ({ initial }) => {
  const [count, setCount] = useState<number>(initial);
  return (
    <div>
      <p>Count: {count}</p>
      <button onClick={() => setCount(count + 1)}>+</button>
    </div>
  );
};

export default function Wrapper(props: Props) {
  return <Counter initial={props.initial} />;
}
