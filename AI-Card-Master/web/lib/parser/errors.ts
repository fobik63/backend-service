export class ParserScrapeError extends Error {
  readonly code:
    | "NOT_FOUND"
    | "TRANSPORT"
    | "NOT_IMPLEMENTED"
    | "ANTIBOT"

  constructor(
    message: string,
    code:
      | "NOT_FOUND"
      | "TRANSPORT"
      | "NOT_IMPLEMENTED"
      | "ANTIBOT" = "TRANSPORT",
  ) {
    super(message)
    this.name = "ParserScrapeError"
    this.code = code
  }
}
