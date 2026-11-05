import type {Request, Response, NextFunction, RequestHandler} from "express";

export class HttpError extends Error {
  constructor(readonly status: number, message: string, readonly details?: unknown) { super(message); }
}
export const endpoint = (fn: (req: Request, res: Response) => unknown | Promise<unknown>): RequestHandler =>
  (req, res, next) => { Promise.resolve().then(() => fn(req, res)).catch(next); };
export function errorHandler(error: unknown, _req: Request, res: Response, next: NextFunction) {
  if (res.headersSent) { next(error); return; }
  if (error instanceof HttpError) { res.status(error.status).json({error: error.message, details: error.details}); return; }
  // Preserve parser errors without exposing stack traces, SQL, or server internals.
  if (error && typeof error === "object" && "status" in error && error.status === 400) {
    res.status(400).json({error: "Invalid request"}); return;
  }
  console.error(error);
  res.status(500).json({error: "Internal server error"});
}
export function requiredText(value: unknown, label: string, maximum = 10000): string {
  if (typeof value !== "string" || !value.trim()) throw new HttpError(400, `${label} is required`);
  if (value.length > maximum) throw new HttpError(400, `${label} is too long`);
  return value.trim();
}
export function positiveInteger(value: unknown, label: string): number {
  const number = Number(value);
  if (!Number.isSafeInteger(number) || number < 1) throw new HttpError(400, `${label} must be a positive integer`);
  return number;
}
