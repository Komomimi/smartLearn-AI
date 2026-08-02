import { useState } from "react";

export default function useLoading(onChange) {
  const [loading, setLoading] = useState(false);
  const setBoth = (v) => {
    setLoading(v);
    onChange(v);
  };
  return [loading, setBoth];
}
