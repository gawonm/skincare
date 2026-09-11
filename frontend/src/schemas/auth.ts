/**
 * 로그인·회원가입 폼의 입력 검증 스키마.
 *
 * 백엔드(`backend/schemas/auth.py`)가 하는 검증을 프론트에서 미리 해서, 뻔한 실수는
 * 네트워크 요청 전에 걸러 준다. 제한 값은 `constants/auth.ts` 에서 가져와 백엔드와
 * 한 벌로 유지한다. 최종 방어선은 여전히 백엔드다.
 *
 * 이메일 소문자 정규화는 백엔드(`_lowercase_email`)가 이미 하므로 여기서 `transform` 을
 * 걸지 않는다. transform 을 넣으면 react-hook-form 의 입력/출력 타입이 갈라져 다루기
 * 번거로워지는데, 그 대가에 비해 얻는 게 없다.
 *
 * `passwordConfirm`·`gender`·`ageGroup`·`termsAgreed` 는 피그마 회원가입 시안(node 93:25)에는
 * 있지만 아직 backend 와 합의 전이라 `POST /auth/signup` 에 실어 보내지 않는다
 * (`docs/contracts/front-to-backend.md` "회원가입 확장" 절, 규칙 16). 화면 검증·상태만
 * 이 스키마가 맡고, 실제 제출은 `SignupPage` 가 합의된 필드만 골라 보낸다.
 */

import { z } from "zod";

import {
  AgeGroup,
  Gender,
  NAME_MAX_LENGTH,
  NAME_MIN_LENGTH,
  PASSWORD_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
} from "../constants/auth";

const emailField = z
  .string()
  .min(1, "이메일을 입력해 주세요.")
  .email("이메일 형식이 올바르지 않습니다.");

const passwordField = z
  .string()
  .min(PASSWORD_MIN_LENGTH, `비밀번호는 ${PASSWORD_MIN_LENGTH}자 이상이어야 합니다.`)
  .max(PASSWORD_MAX_LENGTH, `비밀번호는 ${PASSWORD_MAX_LENGTH}자 이하여야 합니다.`);

const nameField = z
  .string()
  .trim()
  .min(NAME_MIN_LENGTH, "이름을 입력해 주세요.")
  .max(NAME_MAX_LENGTH, `이름은 ${NAME_MAX_LENGTH}자 이하여야 합니다.`);

export const loginSchema = z.object({
  email: emailField,
  password: passwordField,
});

export const signupSchema = z
  .object({
    email: emailField,
    password: passwordField,
    passwordConfirm: passwordField,
    name: nameField,
    gender: z.nativeEnum(Gender, { errorMap: () => ({ message: "성별을 선택해 주세요." }) }),
    ageGroup: z.nativeEnum(AgeGroup, {
      errorMap: () => ({ message: "연령대를 선택해 주세요." }),
    }),
    termsAgreed: z
      .boolean()
      .refine((value) => value, { message: "이용약관 및 개인정보 처리방침에 동의해야 합니다." }),
  })
  .refine((values) => values.password === values.passwordConfirm, {
    message: "비밀번호가 일치하지 않습니다.",
    path: ["passwordConfirm"],
  });

// 폼 값 타입은 스키마에서 추론만 한다(별도 interface 를 두면 두 곳이 어긋날 수 있다).
export type LoginFormValues = z.infer<typeof loginSchema>;
export type SignupFormValues = z.infer<typeof signupSchema>;
