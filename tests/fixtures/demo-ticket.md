# DEMO-1 注文確定画面：割引を合計金額に反映する

> Made-up ticket for testing the testign plugin against the fixture repo built by `make_repo.py`.
> It does not describe any real product.

## 概要

注文確定画面（OrderConfirm）で「確定」ボタンを押したとき、合計金額に割引額を反映する。

## 仕様

1. 合計金額 = 小計 + 消費税 − 割引額
2. 割引額が小計を超える場合、合計金額は 0 円とする。
3. 端数は切り上げる。
4. 請求書の合計金額も同じ計算にする。

## 添付

- Figma: https://www.figma.com/file/EXAMPLE/order-confirm (frame「注文確定」)

## 確認ポイント

- 「確定」ボタン押下後の合計表示
- ポイント利用時の挙動は別チケット（DEMO-2）
