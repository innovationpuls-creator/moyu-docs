/**
 * Type-level import probe (Phase 9 hygiene): every subpath added to
 * @dom/contracts' exports map must resolve under tsc --noEmit. The client-sdk
 * package is the canonical TS consumer of the generated modules (doc 27 §17:
 * apps/web -> client-sdk -> contracts); re-exporting the generated request and
 * response types here locks the map against accidental omission.
 *
 * Generated artifacts live under @dom/contracts/src/** and are never edited;
 * the exports map in @dom/contracts/package.json is the hand-maintained
 * import surface (additive only).
 */

export type { CancelAccountDeletionResponse } from "@dom/contracts/commands/auth/cancel-account-deletion";
export type { Reauthenticate } from "@dom/contracts/commands/auth/reauthenticate";
export type { ReauthenticateResponse } from "@dom/contracts/commands/auth/reauthenticate-response";
export type { RequestAccountDeletionResponse } from "@dom/contracts/commands/auth/request-account-deletion";
export type { RequestPasswordReset } from "@dom/contracts/commands/auth/request-password-reset";
export type { RequestPasswordResetResponse } from "@dom/contracts/commands/auth/request-password-reset-response";
export type { ResendEmailVerification } from "@dom/contracts/commands/auth/resend-email-verification";
export type { ResendEmailVerificationResponse } from "@dom/contracts/commands/auth/resend-email-verification-response";
export type { ResetPassword } from "@dom/contracts/commands/auth/reset-password";
export type { ResetPasswordResponse } from "@dom/contracts/commands/auth/reset-password-response";
export type { VerifyEmail } from "@dom/contracts/commands/auth/verify-email";
export type { VerifyEmailResponse } from "@dom/contracts/commands/auth/verify-email-response";
export type { GetAccountStatusResponse } from "@dom/contracts/queries/auth/get-account-status";
