function stableStringify(value) {
  if (Array.isArray(value)) {
    return `[${value.map(stableStringify).join(",")}]`;
  }
  if (value && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value ?? null);
}

export function createPcuiRefreshGuards({ serializeContext = stableStringify } = {}) {
  const scopes = new Map();

  function begin(scope, context = {}) {
    const scopeKey = String(scope || "default");
    const previous = scopes.get(scopeKey);
    const token = {
      scope: scopeKey,
      id: (previous?.id || 0) + 1,
      contextKey: serializeContext(context),
    };
    scopes.set(scopeKey, token);
    return token;
  }

  function isCurrent(token, currentContext) {
    if (!token) {
      return false;
    }
    const current = scopes.get(token.scope);
    if (!current || current.id !== token.id || current.contextKey !== token.contextKey) {
      return false;
    }
    if (currentContext !== undefined && serializeContext(currentContext) !== token.contextKey) {
      return false;
    }
    return true;
  }

  function getCurrent(scope) {
    return scopes.get(String(scope || "default")) || null;
  }

  function clear(scope) {
    scopes.delete(String(scope || "default"));
  }

  return {
    begin,
    isCurrent,
    getCurrent,
    clear,
  };
}
