param(
  [Parameter(Mandatory=$true)][string]$ImagePath,
  [string]$LanguageTag = 'ko-KR'
)
$ErrorActionPreference='Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = $utf8
[Console]::OutputEncoding = $utf8
try {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $null = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
  $null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime]
  $null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
  $null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
  $null = [Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType=WindowsRuntime]
  $null = [Windows.Media.Ocr.OcrResult, Windows.Media.Ocr, ContentType=WindowsRuntime]
  $null = [Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime]

  $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
      $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    } | Select-Object -First 1)
  if(-not $asTaskGeneric){ throw 'WinRT AsTask helper not found' }
  function Await-WinRt([object]$Operation,[Type]$ResultType){
    $m=$asTaskGeneric.MakeGenericMethod($ResultType)
    $t=$m.Invoke($null,@($Operation))
    $t.Wait(-1) | Out-Null
    if($t.IsFaulted){ throw $t.Exception }
    return $t.Result
  }

  $full=(Resolve-Path -LiteralPath $ImagePath).Path
  $file=Await-WinRt ([Windows.Storage.StorageFile]::GetFileFromPathAsync($full)) ([Windows.Storage.StorageFile])
  $stream=Await-WinRt ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
  $decoder=Await-WinRt ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $bitmap=Await-WinRt ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

  $engine=$null
  if($LanguageTag){
    try {
      $lang=[Windows.Globalization.Language]::new($LanguageTag)
      if([Windows.Media.Ocr.OcrEngine]::IsLanguageSupported($lang)){
        $engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
      }
    } catch {}
  }
  if(-not $engine){ $engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
  if(-not $engine){ throw 'Windows OCR engine unavailable. Korean OCR language pack may be missing.' }
  if($LanguageTag -and $LanguageTag.ToLower().StartsWith('ko') -and -not $engine.RecognizerLanguage.LanguageTag.ToLower().StartsWith('ko')){
    throw ('Korean OCR language is not installed. Current OCR language: ' + $engine.RecognizerLanguage.LanguageTag)
  }

  $result=Await-WinRt ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
  $lines=@()
  foreach($line in $result.Lines){
    $words=@(); $minX=[double]::PositiveInfinity; $minY=[double]::PositiveInfinity; $maxX=0.0; $maxY=0.0
    foreach($word in $line.Words){
      $r=$word.BoundingRect
      $wx=[double]$r.X; $wy=[double]$r.Y; $ww=[double]$r.Width; $wh=[double]$r.Height
      if($wx -lt $minX){$minX=$wx}; if($wy -lt $minY){$minY=$wy}
      if(($wx+$ww) -gt $maxX){$maxX=$wx+$ww}; if(($wy+$wh) -gt $maxY){$maxY=$wy+$wh}
      $words += [pscustomobject]@{text=[string]$word.Text;x=$wx;y=$wy;width=$ww;height=$wh}
    }
    if([double]::IsPositiveInfinity($minX)){ $minX=0;$minY=0;$maxX=0;$maxY=0 }
    $lines += [pscustomobject]@{text=[string]$line.Text;x=$minX;y=$minY;width=($maxX-$minX);height=($maxY-$minY);words=$words}
  }
  [pscustomobject]@{
    ok=$true
    language=[string]$engine.RecognizerLanguage.LanguageTag
    text=[string]$result.Text
    lines=$lines
  } | ConvertTo-Json -Depth 7 -Compress
} catch {
  [pscustomobject]@{ok=$false;error=$_.Exception.Message;lines=@()} | ConvertTo-Json -Depth 4 -Compress
  exit 2
}
