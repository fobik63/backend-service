export class ParserScrapeError extends Error {
  readonly code: "NOT_FOUND" | "TRANSPORT" | "NOT_IMPLEMENTED"

  constructor(
    message: string,
    code: "NOT_FOUND" | "TRANSPORT" | "NOT_IMPLEMENTED" = "TRANSPORT",
  ) {
    super(message)
    this.name = "ParserScrapeError"
    this.code = code
  }
}
