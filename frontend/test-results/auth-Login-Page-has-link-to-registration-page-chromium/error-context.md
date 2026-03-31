# Page snapshot

```yaml
- generic [active] [ref=e1]:
  - generic [ref=e5]:
    - generic [ref=e6]:
      - generic [ref=e7]: SantePublique AOF
      - generic [ref=e8]: Sign in
    - generic [ref=e10]:
      - generic [ref=e11]:
        - generic [ref=e12]: Email address *
        - textbox "Email address *" [ref=e13]:
          - /placeholder: john@example.com
      - generic [ref=e14]:
        - generic [ref=e15]: Authenticator Code *
        - textbox "Authenticator Code *" [ref=e16]:
          - /placeholder: "123456"
        - paragraph [ref=e17]: Enter the 6-digit code from your authenticator app
      - button "Sign in" [ref=e18]
      - button "Lost your authenticator device?" [ref=e20]
      - generic [ref=e21]:
        - generic [ref=e22]: Don't have an account?
        - link "Sign up" [ref=e23] [cursor=pointer]:
          - /url: /undefined/register
  - button "Open Next.js Dev Tools" [ref=e29] [cursor=pointer]:
    - img [ref=e30]
  - alert [ref=e33]
```