def check_password_policy(password: str, *, username: str, min_length: int) -> list[str]:
    """Length-based policy in line with NIST SP 800-63B: no composition rules, no forced rotation."""
    problems: list[str] = []
    if len(password) < min_length:
        problems.append(f"Password must be at least {min_length} characters.")
    if len(password) > 256:
        problems.append("Password must be at most 256 characters.")
    if username and username.lower() in password.lower():
        problems.append("Password must not contain the username.")
    if len(set(password)) < 5:
        problems.append("Password is too repetitive.")
    lowered = password.lower()
    if any(word in lowered for word in ("password", "opsbrain", "qwerty", "123456", "letmein", "admin123")):
        problems.append("Password contains a commonly guessed word or sequence.")
    return problems
