# User Story: User Authentication

## As a registered user
I want to **log in** to the application using my email address and password,  
so that I can securely access my personalised dashboard and manage my account.

---

## Acceptance Criteria

| # | Criteria | Priority |
|---|----------|----------|
| 1 | Given valid credentials, the API returns **HTTP 200** with a signed **JWT access token**. | Must Have |
| 2 | Given invalid credentials, the API returns **HTTP 401** with a descriptive error message. | Must Have |
| 3 | The login endpoint must **NOT** expose the plaintext password in any response field. | Must Have |
| 4 | The JWT token must expire after **60 minutes**. | Should Have |
| 5 | After **5 consecutive failed** login attempts, the account is temporarily locked for 15 minutes. | Should Have |
| 6 | All requests to the login endpoint must be made over **HTTPS**. | Must Have |

---

## Notes
- Authentication uses email + password (no social login in v1).
- Tokens are returned as `Bearer` tokens in the `Authorization` header for subsequent requests.
- Password reset flow is out of scope for this story.
