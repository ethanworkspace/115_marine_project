# Windows PowerShell 5.1 WinRT OCR. Input/output are UTF-8 JSONL; no UI or network.
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Globalization.Language,Windows.Globalization,ContentType=WindowsRuntime]
function Await-Result($operation, [Type]$resultType) {
    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
    $task = $method.MakeGenericMethod($resultType).Invoke($null, @($operation))
    $task.Wait()
    return $task.Result
}
$language = New-Object Windows.Globalization.Language('zh-Hant-TW')
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
if ($null -eq $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
$langs = @([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag })
[Console]::WriteLine((@{ ready=($null -ne $engine); languages=$langs; language=if($engine){$engine.RecognizerLanguage.LanguageTag}else{$null} } | ConvertTo-Json -Compress))
while ($line = [Console]::ReadLine()) {
    $stream = $null
    try {
        $req = $line | ConvertFrom-Json
        if ($null -eq $engine) { throw 'No Windows OCR language is installed' }
        $file = Await-Result ([Windows.Storage.StorageFile]::GetFileFromPathAsync($req.path)) ([Windows.Storage.StorageFile])
        $stream = Await-Result ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
        $decoder = Await-Result ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bitmap = Await-Result ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $result = Await-Result ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
        $lines = @($result.Lines | ForEach-Object { @{ text=$_.Text; words=@($_.Words | ForEach-Object { @{text=$_.Text; x=$_.BoundingRect.X; y=$_.BoundingRect.Y; w=$_.BoundingRect.Width; h=$_.BoundingRect.Height} }) } })
        [Console]::WriteLine((@{id=$req.id;status='OK';text=$result.Text;lines=$lines;language=$engine.RecognizerLanguage.LanguageTag; confidence=$null} | ConvertTo-Json -Depth 8 -Compress))
        $bitmap.Dispose()
    } catch {
        [Console]::WriteLine((@{id=$req.id;status='OCR_ERROR';error=$_.Exception.Message} | ConvertTo-Json -Compress))
    } finally { if ($stream) { $stream.Dispose() } }
}
