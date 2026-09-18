Visual Prompt AI - fixed package

Main fixes:
1. Automatic Telegram monitoring/publishing is preserved.
2. Published posts now use the button label: ✨ Get Prompt
3. The landing page wording is prompt/tutorial focused instead of APK focused.
4. Subscription verification button carries the content ID, so after joining channels
   the bot can immediately deliver the requested media + prompt/tutorial.
5. Python syntax was checked with py_compile.

Deploy the same way as the existing project and keep your existing environment variables.
